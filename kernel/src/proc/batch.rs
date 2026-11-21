//! Owns only the child started for one project batch. Its pipes may leave this
//! module, but only this owner can observe or collect the child.
use std::io;
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus};

pub(crate) struct BatchChild {
    child: Child,
    control: platform::Control,
    end_requested: bool,
}

impl BatchChild {
    pub(crate) fn spawn(command: &mut Command) -> io::Result<Self> {
        let (child, control) = platform::Control::spawn(command)?;
        Ok(Self {
            child,
            control,
            end_requested: false,
        })
    }

    pub(crate) fn take_stdin(&mut self) -> Option<ChildStdin> {
        self.child.stdin.take()
    }

    pub(crate) fn take_stdout(&mut self) -> Option<ChildStdout> {
        self.child.stdout.take()
    }

    /// On Unix this leaves a waitable child in place. On Windows the Job is
    /// owned by its handle independently of collecting the direct child.
    pub(crate) fn observe_exit(&mut self) -> io::Result<bool> {
        self.control.observe_exit(&mut self.child)
    }

    /// Requests cleanup at most once. A successful request does not mean
    /// that every process in the group or Job is gone.
    pub(crate) fn request_end(&mut self) -> io::Result<()> {
        if std::mem::replace(&mut self.end_requested, true) {
            return Err(io::Error::other("the batch cleanup was already attempted"));
        }
        self.control.request_end()
    }

    pub(crate) fn try_collect(&mut self) -> io::Result<Option<ExitStatus>> {
        if !self.end_requested {
            return Err(io::Error::other(
                "the batch cleanup must be decided before collecting",
            ));
        }
        self.child.try_wait()
    }
}

impl Drop for BatchChild {
    fn drop(&mut self) {
        if !self.end_requested {
            let _ = self.request_end();
            let _ = self.try_collect();
        }
    }
}

#[cfg(any(test, unix))]
struct HeldGroup<T>(Option<T>);

#[cfg(any(test, unix))]
impl<T: Copy> HeldGroup<T> {
    fn observe(&mut self, look: impl FnOnce(T) -> io::Result<bool>) -> io::Result<bool> {
        let leader = self.0.ok_or_else(Self::lost)?;
        let seen = look(leader);
        if seen.is_err() {
            self.0 = None;
        }
        seen
    }

    fn request(
        &mut self,
        verify: impl FnOnce(T) -> io::Result<()>,
        signal: impl FnOnce(T) -> io::Result<()>,
    ) -> io::Result<()> {
        let leader = self.0.take().ok_or_else(Self::lost)?;
        verify(leader)?;
        signal(leader)
    }

    fn lost() -> io::Error {
        io::Error::other("the batch process group is no longer owned")
    }
}

#[cfg(all(
    target_pointer_width = "64",
    any(target_arch = "x86_64", target_arch = "aarch64"),
    any(target_os = "macos", all(target_os = "linux", target_env = "gnu"))
))]
mod platform {
    use super::{io, Child, Command, HeldGroup};
    use std::os::unix::process::CommandExt;

    #[cfg(target_os = "macos")]
    const SIGCHLD: i32 = 20;
    #[cfg(target_os = "linux")]
    const SIGCHLD: i32 = 17;
    #[cfg(target_os = "macos")]
    const SA_NOCLDWAIT: i32 = 0x20;
    #[cfg(target_os = "linux")]
    const SA_NOCLDWAIT: i32 = 2;

    // The libc signal-action layouts, from XNU bsd/sys/signal.h and glibc
    // sysdeps/unix/sysv/linux/bits/sigaction.h. We only read the handler's
    // null representation and the flags, and never invoke the handler.
    #[repr(C)]
    #[derive(Default)]
    struct Action {
        handler: usize,
        #[cfg(target_os = "macos")]
        mask: u32,
        #[cfg(target_os = "linux")]
        mask: [u64; 16],
        flags: i32,
        #[cfg(target_os = "linux")]
        restorer: usize,
    }
    #[cfg(target_os = "macos")]
    const _: () = {
        assert!(std::mem::size_of::<Action>() == 16);
        assert!(std::mem::offset_of!(Action, flags) == 12);
    };
    #[cfg(target_os = "linux")]
    const _: () = {
        assert!(std::mem::size_of::<Action>() == 152);
        assert!(std::mem::offset_of!(Action, flags) == 136);
    };

    // The siginfo_t scanner reads only the signed 32-bit si_pid. See XNU
    // bsd/sys/signal.h and glibc sysdeps/unix/sysv/linux/bits/types/siginfo_t.h.
    #[cfg(target_os = "macos")]
    const WAIT_ABI: (usize, usize, i32) = (104, 12, 0x20);
    #[cfg(target_os = "linux")]
    const WAIT_ABI: (usize, usize, i32) = (128, 16, 0x0100_0000);
    const INFO_SIZE: usize = WAIT_ABI.0;
    const PID_OFFSET: usize = WAIT_ABI.1;
    const WNOWAIT: i32 = WAIT_ABI.2;
    #[repr(C, align(8))]
    struct SigInfo([u8; INFO_SIZE]);
    const _: () = {
        assert!(std::mem::size_of::<SigInfo>() == INFO_SIZE);
        assert!(PID_OFFSET + 4 <= INFO_SIZE);
    };

    extern "C" {
        fn sigaction(signal: i32, new: *const Action, old: *mut Action) -> i32;
        fn waitid(kind: u32, id: u32, info: *mut SigInfo, flags: i32) -> i32;
        fn kill(pid: i32, signal: i32) -> i32;
    }

    #[derive(Clone, Copy)]
    struct Leader(i32);

    pub(super) struct Control(HeldGroup<Leader>);

    impl Control {
        pub(super) fn spawn(command: &mut Command) -> io::Result<(Child, Self)> {
            require_waitable_exits()?;
            CommandExt::process_group(command, 0);
            let mut child = command.spawn()?;
            let leader = match i32::try_from(child.id()) {
                Ok(pid) if pid > 1 => Leader(pid),
                _ => {
                    // Impossible for an ordinary direct child on these targets.
                    // Reject without signalling an unverified number.
                    let _ = child.try_wait();
                    return Err(io::Error::other("invalid batch process group leader"));
                }
            };
            Ok((child, Self(HeldGroup(Some(leader)))))
        }

        pub(super) fn observe_exit(&mut self, _child: &mut Child) -> io::Result<bool> {
            self.0.observe(peek)
        }

        pub(super) fn request_end(&mut self) -> io::Result<()> {
            self.0.request(
                |leader| {
                    require_waitable_exits()?;
                    peek(leader)?;
                    Ok(())
                },
                request_group_end,
            )
        }
    }

    fn allows_retained_wait(handler: usize, flags: i32) -> bool {
        handler == 0 && flags & SA_NOCLDWAIT == 0
    }

    fn require_waitable_exits() -> io::Result<()> {
        let mut current = Action::default();
        // SAFETY: this is a read-only query with the supported libc's
        // layout. The null second argument leaves the disposition untouched.
        if unsafe { sigaction(SIGCHLD, std::ptr::null(), &mut current) } != 0 {
            return Err(io::Error::last_os_error());
        }
        // The closed kernel only waits on its own Child instances. A custom
        // handler could reap independently, and auto-reaping would release the
        // child's number even while its Child is private. Require the default
        // disposition both before spawn and immediately before the final look.
        if !allows_retained_wait(current.handler, current.flags) {
            return Err(io::Error::other(
                "batch cleanup requires waitable child exits",
            ));
        }
        Ok(())
    }

    fn peek(leader: Leader) -> io::Result<bool> {
        const P_PID: u32 = 1;
        const WNOHANG: i32 = 1;
        const WEXITED: i32 = 4;
        // Darwin can leave siginfo untouched when no exit is ready.
        let mut info = SigInfo([0; INFO_SIZE]);
        // SAFETY: the zeroed output is owned for the call, with the target's
        // siginfo_t size and alignment. Only our exact direct child is asked.
        if unsafe {
            waitid(
                P_PID,
                leader.0 as u32,
                &mut info,
                WEXITED | WNOHANG | WNOWAIT,
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
        let mut pid = [0; 4];
        pid.copy_from_slice(&info.0[PID_OFFSET..PID_OFFSET + 4]);
        match i32::from_ne_bytes(pid) {
            0 => Ok(false),
            pid if pid == leader.0 => Ok(true),
            _ => Err(io::Error::other("batch wait named a different child")),
        }
    }

    fn request_group_end(leader: Leader) -> io::Result<()> {
        const SIGKILL: i32 = 9;
        const ESRCH: i32 = 3;
        // SAFETY: leader came from this owner's spawn, is greater than one,
        // and is still held across the fresh waitid observation. No wait can
        // collect it before this call.
        if unsafe { kill(-leader.0, SIGKILL) } == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() == Some(ESRCH) {
            return Ok(()); // the system reports no such group while the leader is held
        }
        Err(error)
    }

    #[cfg(test)]
    #[test]
    fn automatic_or_independent_reaping_cannot_grant_group_cleanup() {
        assert!(allows_retained_wait(0, 0));
        assert!(!allows_retained_wait(1, 0));
        assert!(!allows_retained_wait(0, SA_NOCLDWAIT));
    }
}

#[cfg(all(
    unix,
    not(all(
        target_pointer_width = "64",
        any(target_arch = "x86_64", target_arch = "aarch64"),
        any(target_os = "macos", all(target_os = "linux", target_env = "gnu"))
    ))
))]
mod platform {
    use super::{io, Child, Command};

    #[derive(Clone, Copy)]
    pub(super) enum Control {}

    impl Control {
        pub(super) fn spawn(_command: &mut Command) -> io::Result<(Child, Self)> {
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "batch process ownership is unavailable",
            ))
        }

        pub(super) fn observe_exit(&mut self, _child: &mut Child) -> io::Result<bool> {
            match *self {}
        }

        pub(super) fn request_end(&mut self) -> io::Result<()> {
            match *self {}
        }
    }
}

#[cfg(windows)]
mod platform {
    use super::super::windows;
    use super::{io, Child, Command};
    use std::os::windows::io::OwnedHandle;
    use std::os::windows::process::CommandExt;

    pub(super) struct Control(OwnedHandle);

    impl Control {
        pub(super) fn spawn(command: &mut Command) -> io::Result<(Child, Self)> {
            command.creation_flags(windows::CREATE_SUSPENDED);
            let mut child = command.spawn()?;
            match windows::confine_batch(&child) {
                Ok(job) => Ok((child, Self(job))),
                Err(error) => {
                    // This only addresses the direct child via its own handle.
                    let _ = child.kill();
                    let _ = child.try_wait();
                    Err(error)
                }
            }
        }

        pub(super) fn observe_exit(&mut self, child: &mut Child) -> io::Result<bool> {
            child.try_wait().map(|status| status.is_some())
        }

        pub(super) fn request_end(&mut self) -> io::Result<()> {
            windows::request_batch_end(&self.0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::HeldGroup;
    use std::cell::RefCell;
    use std::io;

    #[test]
    fn a_fresh_check_precedes_the_only_group_request() {
        let mut group = HeldGroup(Some(()));
        assert!(group.observe(|()| Ok(true)).unwrap());
        let calls = RefCell::new(Vec::new());
        let verify = |()| {
            calls.borrow_mut().push("verify");
            Ok(())
        };
        let signal = |()| {
            calls.borrow_mut().push("signal");
            Ok(())
        };
        assert!(group.request(verify, signal).is_ok());
        assert!(group.request(verify, signal).is_err());
        assert_eq!(calls.into_inner(), ["verify", "signal"]);
    }

    #[test]
    fn an_old_exit_observation_cannot_authorize_cleanup_after_loss() {
        let mut group = HeldGroup(Some(()));
        assert!(group.observe(|()| Ok(true)).unwrap());
        assert!(group
            .request(|()| Err(io::Error::other("lost")), |()| panic!("no signal"))
            .is_err());
        assert!(group
            .request(|()| panic!("no new look"), |()| panic!("no signal"))
            .is_err());
    }

    #[test]
    fn observation_loss_revokes_the_group_before_cleanup() {
        let mut group = HeldGroup(Some(()));
        assert!(group.observe(|()| Err(io::Error::other("lost"))).is_err());
        assert!(group
            .request(|()| panic!("no new look"), |()| panic!("no signal"))
            .is_err());
    }
}
