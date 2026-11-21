//! Owns only the child started for one project batch. Its pipes may leave this
//! module, but only this owner can observe or collect the child.
use std::io;
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus};
use std::sync::mpsc::{self, SyncSender};

pub(crate) struct BatchChild {
    child: Option<Child>,
    control: platform::Control,
    reaper: SyncSender<Child>,
    end_requested: bool,
    wait_failed: bool,
}

impl BatchChild {
    pub(crate) fn spawn(command: &mut Command) -> io::Result<Self> {
        // Reserve the collector before starting a child. A one-element channel
        // lets us give the same Child to it without waiting on the receiver.
        let (reaper, pending) = mpsc::sync_channel::<Child>(1);
        drop(std::thread::Builder::new().spawn(move || {
            if let Ok(mut child) = pending.recv() {
                let _ = child.wait(); // one owned direct child; this worker never signals
            }
        })?);
        let (child, control) = platform::Control::spawn(command, &reaper)?;
        Ok(Self {
            child: Some(child),
            control,
            reaper,
            end_requested: false,
            wait_failed: false,
        })
    }

    pub(crate) fn take_stdin(&mut self) -> Option<ChildStdin> {
        self.child.as_mut()?.stdin.take()
    }

    pub(crate) fn take_stdout(&mut self) -> Option<ChildStdout> {
        self.child.as_mut()?.stdout.take()
    }

    /// On Unix this leaves a waitable child in place. On Windows the Job is
    /// owned by its handle independently of collecting the direct child.
    pub(crate) fn observe_exit(&mut self) -> io::Result<bool> {
        let child = self.child.as_mut().ok_or_else(no_child)?;
        self.control.observe_exit(child)
    }

    /// Requests cleanup at most once. A successful request does not mean
    /// that every process in the group or Job is gone.
    pub(crate) fn request_end(&mut self) -> io::Result<()> {
        if std::mem::replace(&mut self.end_requested, true) {
            return Err(io::Error::other("the batch cleanup was already attempted"));
        }
        self.control.request_end()
    }

    fn verify_collection(&mut self) -> io::Result<()> {
        if !self.end_requested || self.wait_failed {
            return Err(io::Error::other("batch child collection is unconfirmed"));
        }
        let ownership = self.control.verify_collection();
        self.wait_failed = ownership.is_err();
        ownership
    }

    pub(crate) fn try_collect(&mut self) -> io::Result<Option<ExitStatus>> {
        self.verify_collection()?;
        let status = self.child.as_mut().ok_or_else(no_child)?.try_wait();
        self.wait_failed = status.is_err();
        if matches!(&status, Ok(Some(_))) {
            self.child = None;
        }
        status
    }

    pub(crate) fn defer_collection(&mut self) -> io::Result<()> {
        self.verify_collection()?;
        let transferred = try_transfer(&self.reaper, &mut self.child);
        self.wait_failed = transferred.is_err();
        transferred
    }
}

impl Drop for BatchChild {
    fn drop(&mut self) {
        if !self.end_requested {
            let _ = self.request_end();
        }
        if self.child.is_some() && !self.wait_failed {
            let _ = self.defer_collection();
        }
    }
}

fn no_child() -> io::Error {
    io::Error::other("the batch child is no longer held")
}

fn try_transfer<T>(reaper: &SyncSender<T>, child: &mut Option<T>) -> io::Result<()> {
    let owned = child.take().ok_or_else(no_child)?;
    match reaper.try_send(owned) {
        Ok(()) => Ok(()),
        Err(mpsc::TrySendError::Full(owned) | mpsc::TrySendError::Disconnected(owned)) => {
            *child = Some(owned);
            Err(io::Error::other(
                "the batch child reaper could not take ownership",
            ))
        }
    }
}

#[cfg(any(test, windows))]
const KILL_ON_JOB_CLOSE: u32 = 0x2000;

#[cfg(any(test, windows))]
pub(super) fn prepare_job(
    set: impl FnOnce(u32) -> io::Result<()>,
    read: impl FnOnce() -> io::Result<u32>,
    assign: impl FnOnce() -> io::Result<()>,
    resume: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    set(KILL_ON_JOB_CLOSE)?;
    if read()? & KILL_ON_JOB_CLOSE == 0 {
        return Err(io::Error::other(
            "the batch Job does not have kill-on-close",
        ));
    }
    assign()?;
    resume()
}

#[cfg(any(test, windows))]
fn close_job_after_request<T>(
    job: &mut Option<T>,
    terminate: impl FnOnce(&T) -> io::Result<()>,
) -> io::Result<()> {
    let owned = job
        .take()
        .ok_or_else(|| io::Error::other("the batch Job has closed"))?;
    // The last owned handle closes on either result, before the bounded wait.
    terminate(&owned)
}

#[cfg(any(test, unix))]
struct HeldGroup<T>(Option<T>);

#[cfg(any(test, unix))]
impl<T: Copy> HeldGroup<T> {
    fn observe<R>(&mut self, look: impl FnOnce(T) -> io::Result<R>) -> io::Result<R> {
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
    ) -> io::Result<T> {
        let leader = self.0.take().ok_or_else(Self::lost)?;
        verify(leader)?;
        signal(leader)?;
        Ok(leader)
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
    use super::{io, Child, Command, HeldGroup, SyncSender};
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

    pub(super) struct Control {
        group: HeldGroup<Leader>,
        waitable: HeldGroup<Leader>,
    }

    impl Control {
        pub(super) fn spawn(
            command: &mut Command,
            _reaper: &SyncSender<Child>,
        ) -> io::Result<(Child, Self)> {
            require_waitable_exits()?;
            CommandExt::process_group(command, 0);
            let child = command.spawn()?;
            let leader = match i32::try_from(child.id()) {
                Ok(pid) if pid > 1 => Leader(pid),
                // There is no valid authority to signal or wait on this number.
                _ => return Err(io::Error::other("invalid batch process group leader")),
            };
            Ok((
                child,
                Self {
                    group: HeldGroup(Some(leader)),
                    waitable: HeldGroup(None),
                },
            ))
        }

        pub(super) fn observe_exit(&mut self, _child: &mut Child) -> io::Result<bool> {
            self.group.observe(peek)
        }

        pub(super) fn request_end(&mut self) -> io::Result<()> {
            self.waitable = HeldGroup(Some(
                self.group
                    .request(verify_waitable_child, request_group_end)?,
            ));
            Ok(())
        }

        pub(super) fn verify_collection(&mut self) -> io::Result<()> {
            self.waitable.observe(verify_waitable_child)
        }
    }

    fn verify_waitable_child(leader: Leader) -> io::Result<()> {
        require_waitable_exits()?;
        peek(leader).map(|_| ())
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

    #[cfg(all(test, target_os = "macos"))]
    mod darwin_diagnostic {
        use super::require_waitable_exits;
        use crate::proc::batch::BatchChild;
        use std::io::{self, Read, Write};
        use std::process::{Command, Stdio};
        use std::sync::mpsc;
        use std::time::{Duration, Instant};

        const CHILD: &str = "proc::batch::platform::darwin_diagnostic::probe_child";
        const INPUT: &[u8] = b"{\"runs\":[]}\n";
        const ANSWER: &[u8] = b"{\"ended\":true,\"reports\":[]}\n";
        const LIMIT: Duration = Duration::from_secs(5);

        #[test]
        #[ignore = "run only as the diagnostic's direct child"]
        fn probe_child() -> io::Result<()> {
            let mut input = Vec::new();
            io::stdin().read_to_end(&mut input)?;
            assert_eq!(input, INPUT);
            io::stdout().write_all(ANSWER)?;
            io::stdout().flush()
        }

        fn report<T>(stage: &str, result: io::Result<T>) -> io::Result<T> {
            match &result {
                Ok(_) => eprintln!("batch-diagnostic {stage}: ok"),
                Err(error) => eprintln!(
                    "batch-diagnostic {stage}: kind={:?} raw_os_error={:?} {error}",
                    error.kind(),
                    error.raw_os_error()
                ),
            }
            result
        }

        #[test]
        #[ignore = "focused diagnostic for the macOS batch owner"]
        fn report_owned_batch_stages() -> io::Result<()> {
            report("before-spawn-sigchld", require_waitable_exits())?;
            let mut child = report(
                "spawn",
                BatchChild::spawn(
                    Command::new(std::env::current_exe()?)
                        .args(["--ignored", "--exact", CHILD, "--nocapture"])
                        .stdin(Stdio::piped())
                        .stdout(Stdio::piped())
                        .stderr(Stdio::null()),
                ),
            )?;
            let mut stdout = child.take_stdout().expect("piped diagnostic output");
            let (done, output) = mpsc::sync_channel(1);
            let reader = std::thread::Builder::new().spawn(move || {
                let mut bytes = Vec::new();
                let read = stdout.read_to_end(&mut bytes).map(|_| bytes);
                let _ = done.send(read);
            })?;
            report(
                "write-input",
                child.take_stdin().expect("piped input").write_all(INPUT),
            )?;
            let until = Instant::now() + LIMIT;
            let bytes = report(
                "stdout-eof",
                output
                    .recv_timeout(LIMIT)
                    .map_err(|e| io::Error::new(io::ErrorKind::TimedOut, e))
                    .and_then(|read| read),
            )?;
            reader.join().expect("diagnostic output reader");
            assert!(bytes.windows(ANSWER.len()).any(|window| window == ANSWER));

            let observed = loop {
                match child.observe_exit() {
                    Ok(true) => break Ok(()),
                    Ok(false) if Instant::now() < until => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Ok(false) => {
                        break Err(io::Error::new(
                            io::ErrorKind::TimedOut,
                            "direct exit was not seen",
                        ))
                    }
                    Err(error) => break Err(error),
                }
            };
            let observed = report("waitid-exit", observed);
            let disposition = report("before-cleanup-sigchld", require_waitable_exits());
            let cleanup = report("checked-group-cleanup", child.request_end());
            let collected = report("direct-collect", child.try_collect());
            if let Ok(Some(status)) = &collected {
                eprintln!("batch-diagnostic direct-exit-code: {:?}", status.code());
            }
            observed?;
            disposition?;
            cleanup?;
            assert!(collected?.is_some_and(|status| status.success()));
            Ok(())
        }
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
    use super::{io, Child, Command, SyncSender};

    #[derive(Clone, Copy)]
    pub(super) enum Control {}

    impl Control {
        pub(super) fn spawn(
            _command: &mut Command,
            _reaper: &SyncSender<Child>,
        ) -> io::Result<(Child, Self)> {
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

        pub(super) fn verify_collection(&mut self) -> io::Result<()> {
            match *self {}
        }
    }
}

#[cfg(windows)]
mod platform {
    use super::super::windows;
    use super::{close_job_after_request, io, try_transfer, Child, Command, SyncSender};
    use std::os::windows::io::OwnedHandle;
    use std::os::windows::process::CommandExt;

    pub(super) struct Control(Option<OwnedHandle>);

    impl Control {
        pub(super) fn spawn(
            command: &mut Command,
            reaper: &SyncSender<Child>,
        ) -> io::Result<(Child, Self)> {
            command.creation_flags(windows::CREATE_SUSPENDED);
            let mut child = command.spawn()?;
            match windows::confine_batch(&child) {
                Ok(job) => Ok((child, Self(Some(job)))),
                Err(error) => {
                    // Assignment may have failed. Address only the suspended
                    // direct child via its original process handle.
                    let _ = child.kill();
                    try_transfer(reaper, &mut Some(child))?;
                    Err(error)
                }
            }
        }

        pub(super) fn observe_exit(&mut self, child: &mut Child) -> io::Result<bool> {
            child.try_wait().map(|status| status.is_some())
        }

        pub(super) fn request_end(&mut self) -> io::Result<()> {
            close_job_after_request(&mut self.0, windows::request_batch_end)
        }

        pub(super) fn verify_collection(&mut self) -> io::Result<()> {
            // Child holds the original process handle, independently of the Job.
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{close_job_after_request, prepare_job, try_transfer, HeldGroup, KILL_ON_JOB_CLOSE};
    use std::cell::RefCell;
    use std::io;
    use std::sync::mpsc;

    #[test]
    fn job_close_fallback_is_verified_before_assignment_and_resume() {
        let steps = ["set", "read", "assign", "resume"];
        for (rejected, count) in [
            (None, 4),
            (Some("set"), 1),
            (Some("read"), 2),
            (Some("missing flag"), 2),
            (Some("assign"), 3),
            (Some("resume"), 4),
        ] {
            let calls = RefCell::new(Vec::new());
            let step = |name: &'static str| {
                calls.borrow_mut().push(name);
                if rejected == Some(name) {
                    return Err(io::Error::other(name));
                }
                Ok(())
            };
            let result = prepare_job(
                |flags| {
                    assert_eq!(flags, KILL_ON_JOB_CLOSE);
                    step("set")
                },
                || {
                    step("read")?;
                    Ok(if rejected == Some("missing flag") {
                        0
                    } else {
                        KILL_ON_JOB_CLOSE
                    })
                },
                || step("assign"),
                || step("resume"),
            );
            assert_eq!(result.is_err(), rejected.is_some());
            assert_eq!(calls.into_inner(), steps[..count]);
        }
    }

    #[test]
    fn job_handle_closes_even_when_the_termination_request_fails() {
        struct Job<'a>(&'a RefCell<Vec<&'static str>>);
        impl Drop for Job<'_> {
            fn drop(&mut self) {
                self.0.borrow_mut().push("close");
            }
        }
        for refused in [false, true] {
            let calls = RefCell::new(Vec::new());
            let mut job = Some(Job(&calls));
            let result = close_job_after_request(&mut job, |_| {
                calls.borrow_mut().push("request");
                if refused {
                    return Err(io::Error::other("request refused"));
                }
                Ok(())
            });
            assert_eq!(result.is_err(), refused);
            assert!(job.is_none());
            assert_eq!(*calls.borrow(), ["request", "close"]);
        }
    }

    #[test]
    fn transfer_returns_before_receive_and_preserves_ownership_on_refusal() {
        let (reaper, waiting) = mpsc::sync_channel(1);
        let mut child = Some("owned child");
        try_transfer(&reaper, &mut child).unwrap();
        assert!(child.is_none());
        assert_eq!(waiting.try_recv().unwrap(), "owned child");
        drop(waiting);
        let mut child = Some("still owned");
        assert!(try_transfer(&reaper, &mut child).is_err());
        assert_eq!(child, Some("still owned"));
    }

    #[test]
    fn losing_the_verified_wait_authority_rules_out_collection_or_transfer() {
        let mut group = HeldGroup(Some(()));
        let authority = group.request(|()| Ok(()), |()| Ok(())).unwrap();
        let mut waitable = HeldGroup(Some(authority));
        assert!(waitable
            .observe(|()| Err::<(), _>(io::Error::other("ownership lost")))
            .is_err());
        assert!(waitable
            .observe::<()>(|()| panic!("no repeat observation"))
            .is_err());
    }

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
        assert!(group
            .observe::<bool>(|()| Err(io::Error::other("lost")))
            .is_err());
        assert!(group
            .request(|()| panic!("no new look"), |()| panic!("no signal"))
            .is_err());
    }
}
