//! A process started with everything it starts in turn, so that the whole tree
//! can be ended at once. On Unix the process leads a process group of its own and
//! the group is killed; on Windows the process is started suspended, placed in a
//! job object and only then let run, and the job is terminated.
//!
//! This is the one module with unsafe code: three calls to the operating system,
//! declared here, that the standard library does not offer.
use std::io;
use std::process::{Child, Command};

pub struct Tree {
    pub child: Child,
    ended: bool,
    #[cfg(windows)]
    job: windows::Handle,
}

impl Tree {
    /// Start `command` as the root of a tree that `end` can take down whole.
    pub fn spawn(command: &mut Command) -> io::Result<Tree> {
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
            Ok(Tree {
                child: command.spawn()?,
                ended: false,
            })
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(windows::CREATE_SUSPENDED);
            let child = command.spawn()?;
            let job = windows::confine(&child);
            Ok(Tree {
                child,
                ended: false,
                job,
            })
        }
    }
    /// Whether the root process has ended. What it started may still be running.
    pub fn exited(&mut self) -> bool {
        !matches!(self.child.try_wait(), Ok(None))
    }
    /// End the root and everything it started, and collect the root.
    pub fn end(&mut self) {
        if self.ended {
            return;
        }
        self.ended = true;
        #[cfg(unix)]
        unix::kill_group(self.child.id());
        #[cfg(windows)]
        windows::terminate(self.job);
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for Tree {
    fn drop(&mut self) {
        self.end();
    }
}

#[cfg(unix)]
mod unix {
    extern "C" {
        fn kill(pid: i32, signal: i32) -> i32;
    }
    const SIGKILL: i32 = 9;
    /// Kill every process in the group the process `leader` leads.
    pub fn kill_group(leader: u32) {
        if let Ok(pid) = i32::try_from(leader) {
            if pid > 0 {
                // SAFETY: kill takes two integers and touches no memory of ours.
                unsafe {
                    kill(-pid, SIGKILL);
                }
            }
        }
    }
}

#[cfg(windows)]
mod windows {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    pub type Handle = *mut std::ffi::c_void;
    pub const CREATE_SUSPENDED: u32 = 0x0000_0004;
    const TH32CS_SNAPTHREAD: u32 = 0x0000_0004;
    const THREAD_SUSPEND_RESUME: u32 = 0x0002;
    #[repr(C)]
    struct ThreadEntry32 {
        size: u32,
        usage: u32,
        thread: u32,
        owner: u32,
        base_priority: i32,
        delta_priority: i32,
        flags: u32,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *mut std::ffi::c_void, name: *const u16) -> Handle;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn TerminateJobObject(job: Handle, code: u32) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn CreateToolhelp32Snapshot(flags: u32, process: u32) -> Handle;
        fn Thread32First(snapshot: Handle, entry: *mut ThreadEntry32) -> i32;
        fn Thread32Next(snapshot: Handle, entry: *mut ThreadEntry32) -> i32;
        fn OpenThread(access: u32, inherit: i32, thread: u32) -> Handle;
        fn ResumeThread(thread: Handle) -> u32;
    }
    fn invalid(h: Handle) -> bool {
        h.is_null() || h as isize == -1
    }
    /// Put a process started suspended in a job of its own, then let it run.
    /// Nothing it starts can escape the job, since it starts nothing before it is in it.
    pub fn confine(child: &Child) -> Handle {
        // SAFETY: every pointer passed is either null or points to memory owned here
        // for the length of the call; every handle opened is closed.
        unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if !invalid(job) {
                AssignProcessToJobObject(job, child.as_raw_handle() as Handle);
            }
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
            if !invalid(snapshot) {
                let mut entry = ThreadEntry32 {
                    size: std::mem::size_of::<ThreadEntry32>() as u32,
                    usage: 0,
                    thread: 0,
                    owner: 0,
                    base_priority: 0,
                    delta_priority: 0,
                    flags: 0,
                };
                let mut more = Thread32First(snapshot, &mut entry) != 0;
                while more {
                    if entry.owner == child.id() {
                        let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.thread);
                        if !invalid(thread) {
                            ResumeThread(thread);
                            CloseHandle(thread);
                        }
                    }
                    more = Thread32Next(snapshot, &mut entry) != 0;
                }
                CloseHandle(snapshot);
            }
            job
        }
    }
    pub fn terminate(job: Handle) {
        if !invalid(job) {
            // SAFETY: the handle was opened by `confine` and is closed once, here.
            unsafe {
                TerminateJobObject(job, 1);
                CloseHandle(job);
            }
        }
    }
}
