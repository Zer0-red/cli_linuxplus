#!/usr/bin/env python3
"""
Linux+ XK0-006 Command Dojo
===========================
A SAFE, offline command-practice trainer for the CompTIA Linux+ (XK0-006) exam.

How it keeps you (and your kernel) safe:
  * Nothing you type is ever executed as a shell command.
  * The app ONLY compares your typed answer against the expected command(s).
  * So you can practice `dracut -f`, `mkfs.xfs`, `systemctl mask`, `dd`, etc.
    with zero risk to the real system you are running on.

How a round works:
  1. You get a scenario ("Forcibly rebuild the initramfs image...").
  2. You type the command you think solves it.
  3. Right -> short explanation, on to the next.
     Wrong -> type  :hint  for a nudge (you get several, progressively bigger),
              or  :answer  to reveal it. Then try again as many times as you like.

The matcher is forgiving in the ways the real exam is:
  * optional leading `sudo`
  * flag order doesn't matter        (grep -ri == grep -ir)
  * bundled vs split short flags      (ss -tulpn == ss -t -u -l -p -n)
  * extra whitespace
  * multiple correct forms are accepted (ps aux == ps -ef)

Run:   python3 trainer.py
       python3 trainer.py --reset        (wipe saved progress)
       python3 trainer.py --no-color
"""

import json
import os
import random
import re
import sys
import textwrap

# Bump on EVERY delivered change: major.minor.patch
__version__ = "2.5.2"

# --------------------------------------------------------------------------- #
#  Scenario bank  (all original, written from the published XK0-006 objectives)
#  schema:
#    id          unique key (used for progress tracking)
#    domain      exam domain string
#    topic       short topic label
#    prompt      the scenario the learner must solve
#    accept      list of acceptable command strings (accept[0] is the canonical
#                answer shown on reveal)
#    hints       progressive hints (small -> big)
#    explain     teaching note shown after a correct answer / reveal
#    mode        optional: "smart" (default) | "exact" | "contains" | "regex"
# --------------------------------------------------------------------------- #

SCENARIOS = [
    # ----------------------- 1.0 SYSTEM MANAGEMENT ------------------------- #
    {
        "id": "proc-ps", "domain": "1.0 System Management", "topic": "Processes",
        "prompt": "Display every process running on the system in full detail "
                  "(all users, with the owner, PID and full command line).",
        "accept": ["ps aux", "ps -ef"],
        "hints": ["The classic process snapshot tool is 3 letters.",
                  "Two famous flag styles do this: a BSD style and a System V style.",
                  "BSD: a-u-x  |  System V: -e -f"],
        "explain": "`ps aux` (BSD) and `ps -ef` (System V) both list all processes "
                   "system-wide. `aux` = all + user-oriented + incl. no-tty procs.",
    },
    {
        "id": "proc-kill9", "domain": "1.0 System Management", "topic": "Processes",
        "prompt": "A hung process with PID 4821 won't respond to a normal stop. "
                  "Forcibly terminate it with the KILL signal.",
        "accept": ["kill -9 4821", "kill -KILL 4821", "kill -s 9 4821",
                   "kill -s KILL 4821"],
        "hints": ["Signal 9 is SIGKILL - it cannot be caught or ignored.",
                  "Use the kill command with the signal number.",
                  "kill -9 <PID>"],
        "explain": "Signal 9 (SIGKILL) forcibly ends a process. Try SIGTERM (15) "
                   "first; -9 is the hammer when a process ignores a clean stop.",
    },
    {
        "id": "proc-killall", "domain": "1.0 System Management", "topic": "Processes",
        "prompt": "Kill every running instance of the program named 'nginx' by name.",
        "accept": ["killall nginx", "pkill nginx", "pkill -x nginx"],
        "hints": ["You don't know the PIDs - kill them by name.",
                  "Two tools work by name: killall and pkill.",
                  "killall nginx"],
        "explain": "`killall <name>` and `pkill <pattern>` signal processes by name "
                   "instead of PID (default signal is TERM).",
    },
    {
        "id": "proc-renice", "domain": "1.0 System Management", "topic": "Processes",
        "prompt": "Lower the scheduling priority of the already-running PID 2000 by "
                  "setting its nice value to 10.",
        "accept": ["renice 10 2000", "renice -n 10 2000", "renice 10 -p 2000",
                   "renice -n 10 -p 2000"],
        "hints": ["`nice` sets priority at launch; this process is already running.",
                  "The tool for a running process is `renice`.",
                  "renice 10 2000"],
        "explain": "`renice` changes the niceness of an existing process. Higher nice "
                   "(up to 19) = lower priority. Only root can set negative values.",
    },
    {
        "id": "proc-lsof-port", "domain": "1.0 System Management", "topic": "Processes",
        "prompt": "Find out which process is listening on TCP port 80.",
        "accept": ["lsof -i :80", "lsof -i:80", "ss -tlnp sport = :80"],
        "hints": ["`lsof` lists open files - and network sockets are files.",
                  "The -i flag filters by internet address/port.",
                  "lsof -i :80"],
        "explain": "`lsof -i :80` lists processes with a socket on port 80. "
                   "`ss -tlnp` is the modern alternative for listening sockets.",
    },
    {
        "id": "proc-nohup", "domain": "1.0 System Management", "topic": "Jobs",
        "prompt": "Start the long-running ./backup.sh so it keeps running after you "
                  "log out (immune to hangup), in the background.",
        "accept": ["nohup ./backup.sh &", "nohup bash backup.sh &"],
        "hints": ["You need it to survive the SIGHUP sent when your shell closes.",
                  "Wrap it in `nohup ...` and background it.",
                  "nohup ./backup.sh &"],
        "explain": "`nohup` ignores the hangup signal; trailing `&` backgrounds the "
                   "job so it continues after the session ends.",
    },
    {
        "id": "sched-crontab-edit", "domain": "1.0 System Management", "topic": "Scheduling",
        "prompt": "Open your personal crontab in an editor to add a scheduled job.",
        "accept": ["crontab -e"],
        "hints": ["Per-user scheduled tasks live in the user's crontab.",
                  "The flag to edit it is -e.",
                  "crontab -e"],
        "explain": "`crontab -e` edits your user crontab; `crontab -l` lists it. "
                   "System-wide jobs live in /etc/crontab and /etc/cron.d/.",
    },
    {
        "id": "dev-modprobe", "domain": "1.0 System Management", "topic": "Kernel modules",
        "prompt": "Load the kernel module named 'vfio' into the running kernel "
                  "(resolving its dependencies automatically).",
        "accept": ["modprobe vfio"],
        "hints": ["`insmod` loads a single .ko but ignores dependencies.",
                  "The dependency-aware loader is `modprobe`.",
                  "modprobe vfio"],
        "explain": "`modprobe` loads a module AND its dependencies (using modules.dep). "
                   "`insmod` loads one file with no dependency handling.",
    },
    {
        "id": "dev-modprobe-r", "domain": "1.0 System Management", "topic": "Kernel modules",
        "prompt": "Unload the currently loaded kernel module 'pcspkr'.",
        "accept": ["modprobe -r pcspkr", "rmmod pcspkr"],
        "hints": ["Two tools can remove a module.",
                  "modprobe with -r, or the simpler rmmod.",
                  "modprobe -r pcspkr"],
        "explain": "`modprobe -r` removes a module and unneeded dependencies; "
                   "`rmmod` removes just the one module.",
    },
    {
        "id": "dev-modinfo", "domain": "1.0 System Management", "topic": "Kernel modules",
        "prompt": "Show detailed information (parameters, dependencies, license) for "
                  "the 'e1000e' kernel module.",
        "accept": ["modinfo e1000e"],
        "hints": ["`lsmod` only lists loaded modules - you need detail.",
                  "Use `modinfo <module>`.",
                  "modinfo e1000e"],
        "explain": "`modinfo` prints a module's metadata: filename, author, params, "
                   "and dependencies - even if it's not currently loaded.",
    },
    {
        "id": "dev-dracut", "domain": "1.0 System Management", "topic": "initrd",
        "prompt": "Forcibly rebuild the current kernel's initramfs image, overwriting "
                  "the existing one.",
        "accept": ["dracut -f", "dracut --force"],
        "hints": ["The modern initramfs generator is `dracut`.",
                  "You must force it to overwrite the existing image.",
                  "dracut -f"],
        "explain": "`dracut -f` regenerates and overwrites the initramfs. Run it after "
                   "changing drivers/modules needed at early boot. (Debian uses "
                   "`update-initramfs -u`.)",
    },
    {
        "id": "dev-lsblk", "domain": "1.0 System Management", "topic": "Devices",
        "prompt": "Display all block devices in a tree, showing their mount points.",
        "accept": ["lsblk"],
        "hints": ["You want a tree of disks and partitions.",
                  "It starts with 'ls' and ends in 'blk'.",
                  "lsblk"],
        "explain": "`lsblk` shows block devices as a tree with size, type and mount "
                   "point - great for spotting unmounted or new disks.",
    },
    {
        "id": "dev-dmesg", "domain": "1.0 System Management", "topic": "Devices",
        "prompt": "View the kernel ring buffer to read messages about hardware "
                  "detected at boot (human-readable timestamps).",
        "accept": ["dmesg -T", "dmesg --ctime"],
        "hints": ["Kernel/hardware messages live in the kernel ring buffer.",
                  "The tool is `dmesg`; -T gives readable timestamps.",
                  "dmesg -T"],
        "explain": "`dmesg` prints the kernel ring buffer. `-T` converts the raw "
                   "seconds-since-boot to human time.",
    },
    {
        "id": "lvm-pvcreate", "domain": "1.0 System Management", "topic": "LVM",
        "prompt": "Initialize the new disk /dev/sdb as an LVM physical volume.",
        "accept": ["pvcreate /dev/sdb"],
        "hints": ["LVM layers: physical volume -> volume group -> logical volume.",
                  "Step one creates the *physical volume*.",
                  "pvcreate /dev/sdb"],
        "explain": "`pvcreate` tags a disk/partition as an LVM PV - the first step "
                   "before adding it to a volume group.",
    },
    {
        "id": "lvm-vgcreate", "domain": "1.0 System Management", "topic": "LVM",
        "prompt": "Create a volume group named 'datavg' using the physical volume "
                  "/dev/sdb.",
        "accept": ["vgcreate datavg /dev/sdb"],
        "hints": ["Group one or more PVs into a volume group.",
                  "Syntax is: vgcreate <vgname> <pv...>",
                  "vgcreate datavg /dev/sdb"],
        "explain": "`vgcreate <name> <pv>` pools physical volumes into a volume group "
                   "from which logical volumes are carved.",
    },
    {
        "id": "lvm-lvcreate", "domain": "1.0 System Management", "topic": "LVM",
        "prompt": "Carve a 20 GB logical volume named 'web' out of the volume group "
                  "'datavg'.",
        "accept": ["lvcreate -L 20G -n web datavg", "lvcreate -n web -L 20G datavg"],
        "hints": ["Use -L for a fixed size and -n for the name.",
                  "Order: lvcreate -L <size> -n <name> <vg>",
                  "lvcreate -L 20G -n web datavg"],
        "explain": "`lvcreate -L 20G -n web datavg` creates LV 'web'. Use -l (lowercase) "
                   "for extents/percentages, e.g. -l 100%FREE.",
    },
    {
        "id": "lvm-lvextend", "domain": "1.0 System Management", "topic": "LVM",
        "prompt": "Grow the logical volume /dev/datavg/web by an additional 5 GB and "
                  "resize its ext4 filesystem in the same step.",
        "accept": ["lvextend -L +5G -r /dev/datavg/web",
                   "lvextend -r -L +5G /dev/datavg/web",
                   "lvextend --resizefs -L +5G /dev/datavg/web"],
        "hints": ["`+5G` means add to the current size.",
                  "The -r (--resizefs) flag grows the filesystem too.",
                  "lvextend -L +5G -r /dev/datavg/web"],
        "explain": "`lvextend -L +5G -r` extends the LV and resizes the filesystem in "
                   "one go. Without -r you'd follow up with resize2fs / xfs_growfs.",
    },
    {
        "id": "fs-resize2fs", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "After enlarging the LV, grow the ext4 filesystem on "
                  "/dev/datavg/web to fill the space.",
        "accept": ["resize2fs /dev/datavg/web"],
        "hints": ["ext2/3/4 filesystems are grown with one specific tool.",
                  "It's resize2fs.",
                  "resize2fs /dev/datavg/web"],
        "explain": "`resize2fs` grows (or shrinks, when unmounted) ext filesystems. "
                   "For XFS you'd use `xfs_growfs <mountpoint>` (XFS only grows).",
    },
    {
        "id": "fs-xfsgrow", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "Grow the XFS filesystem mounted at /data to use the newly added "
                  "space.",
        "accept": ["xfs_growfs /data"],
        "hints": ["XFS uses its own grow tool, and it takes the mount point.",
                  "xfs_growfs <mountpoint>",
                  "xfs_growfs /data"],
        "explain": "`xfs_growfs <mountpoint>` expands a mounted XFS filesystem. XFS "
                   "cannot be shrunk - only grown.",
    },
    {
        "id": "fs-mkfs", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "Format the partition /dev/sdc1 with an ext4 filesystem.",
        "accept": ["mkfs.ext4 /dev/sdc1", "mkfs -t ext4 /dev/sdc1"],
        "hints": ["The make-filesystem family is `mkfs`.",
                  "Either mkfs.ext4 ... or mkfs -t ext4 ...",
                  "mkfs.ext4 /dev/sdc1"],
        "explain": "`mkfs.ext4 /dev/sdc1` (or `mkfs -t ext4`) creates the filesystem. "
                   "This erases the partition - hence why we practice it safely here!",
    },
    {
        "id": "fs-mount-opts", "domain": "1.0 System Management", "topic": "Mounting",
        "prompt": "Temporarily mount /dev/sdc1 at /mnt/data, read-only.",
        "accept": ["mount -o ro /dev/sdc1 /mnt/data",
                   "mount -r /dev/sdc1 /mnt/data"],
        "hints": ["Use -o to pass mount options.",
                  "The read-only option is `ro` (or use -r).",
                  "mount -o ro /dev/sdc1 /mnt/data"],
        "explain": "`mount -o ro <device> <dir>` mounts read-only. Persistent mounts "
                   "go in /etc/fstab.",
    },
    {
        "id": "fs-df", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "Show free and used space on all mounted filesystems in human-"
                  "readable units (GB/MB).",
        "accept": ["df -h", "df -H"],
        "hints": ["The disk-free tool is two letters.",
                  "Add -h for human-readable sizes.",
                  "df -h"],
        "explain": "`df -h` reports filesystem usage in human units. `du -sh <dir>` "
                   "instead summarizes the size of a directory tree.",
    },
    {
        "id": "fs-du", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "Show the total size of the /var/log directory as a single human-"
                  "readable figure.",
        "accept": ["du -sh /var/log", "du -hs /var/log"],
        "hints": ["`du` estimates directory size.",
                  "-s summarizes (one total), -h makes it human-readable.",
                  "du -sh /var/log"],
        "explain": "`du -sh <dir>` gives one summarized, human-readable total for a "
                   "directory - perfect for hunting space hogs.",
    },
    {
        "id": "fs-fsck", "domain": "1.0 System Management", "topic": "Filesystems",
        "prompt": "Check and repair the filesystem on the unmounted partition "
                  "/dev/sdc1.",
        "accept": ["fsck /dev/sdc1", "fsck -y /dev/sdc1"],
        "hints": ["File System ChecK.",
                  "fsck <device>  (-y auto-answers yes to fixes).",
                  "fsck /dev/sdc1"],
        "explain": "`fsck` checks/repairs a filesystem - the device MUST be unmounted "
                   "to avoid corruption. `-y` answers 'yes' to all repairs.",
    },
    {
        "id": "shell-grep", "domain": "1.0 System Management", "topic": "Text tools",
        "prompt": "Recursively search every file under /var/log for the word 'error', "
                  "ignoring case.",
        "accept": ["grep -ri error /var/log", "grep -ri 'error' /var/log",
                   "grep -r -i error /var/log"],
        "hints": ["-r = recurse into directories, -i = ignore case.",
                  "grep <flags> <pattern> <path>",
                  "grep -ri error /var/log"],
        "explain": "`grep -ri error /var/log` recurses (-r) and ignores case (-i). "
                   "Add -n to show line numbers, -l to list just filenames.",
    },
    {
        "id": "shell-find-size", "domain": "1.0 System Management", "topic": "Text tools",
        "prompt": "Find all files larger than 100 MB anywhere on the system.",
        "accept": ["find / -size +100M", "find / -type f -size +100M"],
        "hints": ["`find` searches the tree; -size filters by size.",
                  "+100M means 'greater than 100 megabytes'.",
                  "find / -size +100M"],
        "explain": "`find / -size +100M` locates large files. The `+` means greater "
                   "than; M = MiB. Add `-type f` to limit to regular files.",
    },
    {
        "id": "shell-stderr", "domain": "1.0 System Management", "topic": "Redirection",
        "prompt": "Run ./build.sh and send ONLY its error output (stderr) to a file "
                  "called errors.log.",
        "accept": ["./build.sh 2> errors.log", "./build.sh 2>errors.log",
                   "bash build.sh 2> errors.log"],
        "mode": "contains",
        "hints": ["stdout is file descriptor 1; stderr is file descriptor 2.",
                  "Redirect FD 2 with `2>`.",
                  "./build.sh 2> errors.log"],
        "explain": "`2>` redirects stderr (FD 2). `2>&1` merges stderr into stdout; "
                   "`&>file` sends both to one file.",
    },
    {
        "id": "shell-sort-uniq", "domain": "1.0 System Management", "topic": "Text tools",
        "prompt": "Take access.log, count how many times each unique line appears, "
                  "using a sort piped into a uniq count.",
        "accept": ["sort access.log | uniq -c", "sort < access.log | uniq -c"],
        "mode": "contains",
        "hints": ["`uniq -c` counts adjacent duplicate lines.",
                  "uniq needs sorted input first, so sort, then pipe to uniq -c.",
                  "sort access.log | uniq -c"],
        "explain": "`uniq` only collapses ADJACENT duplicates, so you `sort` first. "
                   "`uniq -c` prefixes each line with its count.",
    },
    {
        "id": "backup-tar-create", "domain": "1.0 System Management", "topic": "Backup",
        "prompt": "Create a gzip-compressed tar archive named backup.tar.gz containing "
                  "the /etc directory.",
        "accept": ["tar -czvf backup.tar.gz /etc", "tar -czf backup.tar.gz /etc",
                   "tar czvf backup.tar.gz /etc", "tar czf backup.tar.gz /etc"],
        "hints": ["Think C-Z-F: Create, gZip, File.",
                  "The filename comes right after -f.",
                  "tar -czvf backup.tar.gz /etc"],
        "explain": "`tar -czf backup.tar.gz /etc`: -c create, -z gzip, -f file. "
                   "Add -v for verbose. To extract: swap -c for -x.",
    },
    {
        "id": "backup-tar-extract", "domain": "1.0 System Management", "topic": "Backup",
        "prompt": "Extract the gzip-compressed archive backup.tar.gz into the current "
                  "directory.",
        "accept": ["tar -xzvf backup.tar.gz", "tar -xzf backup.tar.gz",
                   "tar xzvf backup.tar.gz", "tar xzf backup.tar.gz"],
        "hints": ["eXtract instead of Create.",
                  "x-z-f: eXtract, gZip, File.",
                  "tar -xzf backup.tar.gz"],
        "explain": "`tar -xzf backup.tar.gz` extracts a gzipped archive. -C <dir> "
                   "extracts somewhere other than the current directory.",
    },
    {
        "id": "backup-rsync", "domain": "1.0 System Management", "topic": "Backup",
        "prompt": "Mirror /home/data/ to the remote host backup01 under /srv/data, "
                  "preserving permissions and compressing during transfer.",
        "accept": ["rsync -avz /home/data/ backup01:/srv/data",
                   "rsync -avz /home/data/ backup01:/srv/data/"],
        "hints": ["-a archive (perms/times), -v verbose, -z compress.",
                  "rsync -avz <src> <user@host:dest>",
                  "rsync -avz /home/data/ backup01:/srv/data"],
        "explain": "`rsync -avz` = archive + verbose + compress. The trailing slash on "
                   "the source copies its *contents* rather than the folder itself.",
    },
    {
        "id": "backup-gzip", "domain": "1.0 System Management", "topic": "Compression",
        "prompt": "Compress the file huge.log in place using gzip.",
        "accept": ["gzip huge.log"],
        "hints": ["The classic single-file compressor.",
                  "gzip <file>  (replaces it with file.gz).",
                  "gzip huge.log"],
        "explain": "`gzip huge.log` replaces it with huge.log.gz. Decompress with "
                   "`gunzip` or `gzip -d`. `zcat`/`zgrep` read .gz without unpacking.",
    },
    {
        "id": "virt-virsh-list", "domain": "1.0 System Management", "topic": "Virtualization",
        "prompt": "List all libvirt virtual machines, including ones that are powered "
                  "off.",
        "accept": ["virsh list --all"],
        "hints": ["The libvirt CLI is `virsh`.",
                  "Plain `virsh list` shows only running VMs - add --all.",
                  "virsh list --all"],
        "explain": "`virsh list --all` shows every defined domain and its state. "
                   "`virsh start <name>` / `virsh shutdown <name>` control them.",
    },

    # --------------- 2.0 SERVICES & USER MANAGEMENT ------------------------ #
    {
        "id": "sd-enable-now", "domain": "2.0 Services and User Management",
        "topic": "systemd",
        "prompt": "Enable the sshd service to start at boot AND start it right now, in "
                  "a single command.",
        "accept": ["systemctl enable --now sshd", "systemctl enable --now sshd.service"],
        "hints": ["`enable` sets boot start; `start` starts it now.",
                  "There's a flag that does both at once.",
                  "systemctl enable --now sshd"],
        "explain": "`systemctl enable --now sshd` enables at boot and starts "
                   "immediately. The `.service` suffix is optional.",
    },
    {
        "id": "sd-status", "domain": "2.0 Services and User Management", "topic": "systemd",
        "prompt": "Check whether the nginx service is active and view its recent log "
                  "lines.",
        "accept": ["systemctl status nginx", "systemctl status nginx.service"],
        "hints": ["One subcommand shows active/inactive plus recent logs.",
                  "systemctl status <unit>",
                  "systemctl status nginx"],
        "explain": "`systemctl status <unit>` shows load/active state, the main PID, "
                   "and the last several journal lines for that unit.",
    },
    {
        "id": "sd-daemon-reload", "domain": "2.0 Services and User Management",
        "topic": "systemd",
        "prompt": "You just edited a unit file by hand in /etc/systemd/system. Make "
                  "systemd re-read its unit configuration.",
        "accept": ["systemctl daemon-reload"],
        "hints": ["systemd caches unit files in memory.",
                  "You must reload the systemd *manager* configuration.",
                  "systemctl daemon-reload"],
        "explain": "`systemctl daemon-reload` reloads systemd's view of unit files "
                   "after manual edits. (Different from reloading a service itself.)",
    },
    {
        "id": "sd-mask", "domain": "2.0 Services and User Management", "topic": "systemd",
        "prompt": "Completely prevent the bluetooth service from ever being started, "
                  "even manually or by another unit.",
        "accept": ["systemctl mask bluetooth", "systemctl mask bluetooth.service"],
        "hints": ["`disable` only stops it at boot - it can still be started.",
                  "To make it un-startable, you *mask* it.",
                  "systemctl mask bluetooth"],
        "explain": "`mask` links the unit to /dev/null so it cannot start at all. "
                   "Reverse it with `systemctl unmask`.",
    },
    {
        "id": "log-journalctl-unit", "domain": "2.0 Services and User Management",
        "topic": "Logging",
        "prompt": "Show only the journald log entries for the sshd service, from the "
                  "current boot.",
        "accept": ["journalctl -u sshd -b", "journalctl -b -u sshd",
                   "journalctl -u sshd.service -b"],
        "hints": ["-u filters by unit; -b limits to this boot.",
                  "journalctl -u <unit> -b",
                  "journalctl -u sshd -b"],
        "explain": "`journalctl -u sshd -b` filters by unit (-u) for the current boot "
                   "(-b). `-b -1` would be the previous boot.",
    },
    {
        "id": "log-journalctl-follow", "domain": "2.0 Services and User Management",
        "topic": "Logging",
        "prompt": "Tail the system journal live, watching new entries appear in real "
                  "time.",
        "accept": ["journalctl -f", "journalctl --follow"],
        "hints": ["Like `tail -f`, but for the journal.",
                  "The follow flag is -f.",
                  "journalctl -f"],
        "explain": "`journalctl -f` follows the journal live. `journalctl -k` limits "
                   "to kernel messages; `-p err` filters by priority.",
    },
    {
        "id": "sw-apt-install", "domain": "2.0 Services and User Management",
        "topic": "Software",
        "prompt": "On a Debian/Ubuntu host, install the package 'htop'.",
        "accept": ["apt install htop", "apt-get install htop"],
        "hints": ["Debian-family package manager.",
                  "apt install <package>",
                  "apt install htop"],
        "explain": "`apt install htop` installs the package. Run `apt update` first to "
                   "refresh the package index. Red Hat family uses `dnf install`.",
    },
    {
        "id": "sw-dnf-install", "domain": "2.0 Services and User Management",
        "topic": "Software",
        "prompt": "On a RHEL/Rocky/Fedora host, install the package 'httpd'.",
        "accept": ["dnf install httpd", "yum install httpd"],
        "hints": ["Red Hat family package manager (the modern one).",
                  "dnf install <package>",
                  "dnf install httpd"],
        "explain": "`dnf install httpd` (yum is the older alias). `dnf check-update` "
                   "shows updates; `rpm -qa` lists installed packages.",
    },
    {
        "id": "user-useradd", "domain": "2.0 Services and User Management", "topic": "Users",
        "prompt": "Create the user 'alice' with a home directory and bash as her login "
                  "shell.",
        "accept": ["useradd -m -s /bin/bash alice", "useradd -s /bin/bash -m alice"],
        "hints": ["-m creates the home directory; -s sets the login shell.",
                  "useradd -m -s /bin/bash <name>",
                  "useradd -m -s /bin/bash alice"],
        "explain": "`useradd -m -s /bin/bash alice` makes the account, its home dir "
                   "(-m), and sets the shell (-s). Then set a password with `passwd`.",
    },
    {
        "id": "user-usermod-group", "domain": "2.0 Services and User Management",
        "topic": "Users",
        "prompt": "Add the existing user 'alice' to the 'docker' group WITHOUT removing "
                  "her from any of her current groups.",
        "accept": ["usermod -aG docker alice", "usermod -a -G docker alice",
                   "usermod -G docker -a alice"],
        "hints": ["Just -G would REPLACE her group list - dangerous.",
                  "The -a (append) flag is the key, alongside -G.",
                  "usermod -aG docker alice"],
        "explain": "`usermod -aG <group> <user>` APPENDS a supplementary group. "
                   "Forgetting -a wipes existing memberships - a classic gotcha.",
    },
    {
        "id": "user-lock", "domain": "2.0 Services and User Management", "topic": "Users",
        "prompt": "Lock the account 'bob' so he can no longer log in with his password.",
        "accept": ["usermod -L bob", "passwd -l bob", "usermod --lock bob"],
        "hints": ["Two tools can lock a password.",
                  "usermod -L <user>  or  passwd -l <user>",
                  "usermod -L bob"],
        "explain": "`usermod -L` / `passwd -l` lock the password (prepend ! in shadow). "
                   "Unlock with -U / -u.",
    },
    {
        "id": "ctr-run", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "Run an nginx container in the background, mapping host port 8080 to "
                  "container port 80.",
        "accept": ["podman run -d -p 8080:80 nginx", "docker run -d -p 8080:80 nginx",
                   "podman run -p 8080:80 -d nginx", "docker run -p 8080:80 -d nginx"],
        "hints": ["-d detaches (background); -p maps ports host:container.",
                  "<runtime> run -d -p 8080:80 <image>",
                  "podman run -d -p 8080:80 nginx"],
        "explain": "`podman run -d -p 8080:80 nginx` (docker works identically). "
                   "-d = detached, -p host:container publishes the port.",
    },
    {
        "id": "ctr-ps", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "List ALL containers, including ones that have stopped.",
        "accept": ["podman ps -a", "docker ps -a", "podman ps --all", "docker ps --all"],
        "hints": ["Plain `ps` shows only running containers.",
                  "Add -a (all) to include stopped ones.",
                  "podman ps -a"],
        "explain": "`podman ps -a` (or docker) lists every container regardless of "
                   "state. Without -a you only see running ones.",
    },
    {
        "id": "ctr-logs", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "Read the logs of the running container named 'web'.",
        "accept": ["podman logs web", "docker logs web"],
        "hints": ["Containers send stdout/stderr to a logs subcommand.",
                  "<runtime> logs <name>",
                  "podman logs web"],
        "explain": "`podman logs web` shows the container's captured stdout/stderr. "
                   "Add -f to follow live.",
    },
    {
        "id": "ctr-exec", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "Open an interactive bash shell inside the running container named "
                  "'web'.",
        "accept": ["podman exec -it web bash", "docker exec -it web bash",
                   "podman exec -i -t web bash", "docker exec -i -t web bash"],
        "hints": ["`exec` runs a command in an existing container.",
                  "-i keeps stdin open, -t allocates a TTY: -it.",
                  "podman exec -it web bash"],
        "explain": "`podman exec -it web bash` runs an interactive shell in a live "
                   "container. (`run` would start a NEW container instead.)",
    },
    {
        "id": "ctr-build", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "Build a container image tagged 'myapp:1.0' from the Dockerfile in "
                  "the current directory.",
        "accept": ["podman build -t myapp:1.0 .", "docker build -t myapp:1.0 .",
                   "podman build --tag myapp:1.0 .", "docker build --tag myapp:1.0 ."],
        "hints": ["-t tags the image; the final `.` is the build context.",
                  "<runtime> build -t name:tag .",
                  "podman build -t myapp:1.0 ."],
        "explain": "`podman build -t myapp:1.0 .` builds from ./Dockerfile and tags the "
                   "result. Don't forget the trailing `.` (the build context).",
    },
    {
        "id": "ctr-prune", "domain": "2.0 Services and User Management", "topic": "Containers",
        "prompt": "Remove all unused (dangling) container images to reclaim space.",
        "accept": ["podman image prune", "docker image prune"],
        "hints": ["The cleanup verb is 'prune'.",
                  "<runtime> image prune",
                  "podman image prune"],
        "explain": "`podman image prune` deletes dangling images. `system prune` goes "
                   "further (stopped containers, unused networks/volumes too).",
    },

    # --------------------------- 3.0 SECURITY ------------------------------ #
    {
        "id": "sec-chmod-octal", "domain": "3.0 Security", "topic": "Permissions",
        "prompt": "Set the permissions of script.sh to rwx for the owner and r-x for "
                  "group and others (using octal notation).",
        "accept": ["chmod 755 script.sh"],
        "hints": ["rwx=7, r-x=5. Owner/group/other -> three digits.",
                  "chmod 755 <file>",
                  "chmod 755 script.sh"],
        "explain": "`chmod 755`: owner rwx(7), group r-x(5), other r-x(5). r=4, w=2, "
                   "x=1 added together per column.",
    },
    {
        "id": "sec-chmod-symbolic", "domain": "3.0 Security", "topic": "Permissions",
        "prompt": "Add execute permission for the owner of deploy.sh, using symbolic "
                  "notation.",
        "accept": ["chmod u+x deploy.sh"],
        "hints": ["u=user/owner, g=group, o=other, a=all.",
                  "Add (+) the execute (x) bit for the user (u).",
                  "chmod u+x deploy.sh"],
        "explain": "`chmod u+x` adds execute for the owner only. `+x` (no who) would "
                   "add it for all categories subject to umask.",
    },
    {
        "id": "sec-chown", "domain": "3.0 Security", "topic": "Permissions",
        "prompt": "Change the owner of report.txt to 'alice' and the group to 'staff' "
                  "in one command.",
        "accept": ["chown alice:staff report.txt", "chown alice.staff report.txt"],
        "hints": ["chown can set user and group together with a colon.",
                  "chown user:group <file>",
                  "chown alice:staff report.txt"],
        "explain": "`chown alice:staff report.txt` sets both owner and group. Use -R "
                   "to recurse through a directory tree.",
    },
    {
        "id": "sec-setfacl", "domain": "3.0 Security", "topic": "ACLs",
        "prompt": "Grant the user 'bob' read and write access to project.txt via an "
                  "access control list, without changing the file's owner or group.",
        "accept": ["setfacl -m u:bob:rw project.txt", "setfacl -m u:bob:rw- project.txt"],
        "hints": ["ACLs are managed with setfacl; -m modifies an entry.",
                  "Entry format: u:<user>:<perms>",
                  "setfacl -m u:bob:rw project.txt"],
        "explain": "`setfacl -m u:bob:rw project.txt` adds an ACL entry for one user. "
                   "View ACLs with `getfacl`; files with ACLs show a `+` in `ls -l`.",
    },
    {
        "id": "sec-chattr", "domain": "3.0 Security", "topic": "Attributes",
        "prompt": "Make the file /etc/resolv.conf immutable so that even root cannot "
                  "modify or delete it until the attribute is removed.",
        "accept": ["chattr +i /etc/resolv.conf"],
        "hints": ["Change ATTRibutes -> chattr.",
                  "The immutable attribute is 'i'; add it with +.",
                  "chattr +i /etc/resolv.conf"],
        "explain": "`chattr +i` sets the immutable flag (view with `lsattr`). Remove it "
                   "with `chattr -i`. Even root must clear it before editing.",
    },
    {
        "id": "sec-setenforce", "domain": "3.0 Security", "topic": "SELinux",
        "prompt": "Temporarily switch SELinux into permissive mode (logging denials "
                  "but not blocking), without rebooting.",
        "accept": ["setenforce 0", "setenforce Permissive", "setenforce permissive"],
        "hints": ["Permissive corresponds to 0; Enforcing to 1.",
                  "setenforce 0",
                  "setenforce 0"],
        "explain": "`setenforce 0` = permissive (denials logged only); `setenforce 1` = "
                   "enforcing. Check with `getenforce`. Persistent change: /etc/selinux/config.",
    },
    {
        "id": "sec-restorecon", "domain": "3.0 Security", "topic": "SELinux",
        "prompt": "Recursively reset the SELinux security contexts under /var/www to "
                  "their policy defaults (verbose output).",
        "accept": ["restorecon -Rv /var/www", "restorecon -rv /var/www",
                   "restorecon -vR /var/www"],
        "hints": ["You're restoring contexts to the policy's default.",
                  "restorecon -R (recursive) -v (verbose) <path>",
                  "restorecon -Rv /var/www"],
        "explain": "`restorecon -Rv /var/www` re-labels files to match policy - the fix "
                   "when a web server gets 'permission denied' despite correct modes.",
    },
    {
        "id": "sec-setsebool", "domain": "3.0 Security", "topic": "SELinux",
        "prompt": "Persistently enable the SELinux boolean that lets httpd make network "
                  "connections (so it survives a reboot).",
        "accept": ["setsebool -P httpd_can_network_connect on",
                   "setsebool -P httpd_can_network_connect 1"],
        "hints": ["Booleans toggle policy features at runtime.",
                  "The -P flag makes the change permanent.",
                  "setsebool -P httpd_can_network_connect on"],
        "explain": "`setsebool -P <bool> on` flips a boolean permanently (-P writes to "
                   "policy). Without -P it reverts on reboot. List with `getsebool -a`.",
    },
    {
        "id": "sec-firewalld-port", "domain": "3.0 Security", "topic": "firewalld",
        "prompt": "Permanently open TCP port 443 in firewalld (the change should "
                  "persist across reloads).",
        "accept": ["firewall-cmd --permanent --add-port=443/tcp",
                   "firewall-cmd --add-port=443/tcp --permanent"],
        "hints": ["firewalld's CLI is firewall-cmd.",
                  "--permanent persists; --add-port=PORT/PROTO opens it.",
                  "firewall-cmd --permanent --add-port=443/tcp"],
        "explain": "`firewall-cmd --permanent --add-port=443/tcp` writes the rule; "
                   "follow with `firewall-cmd --reload` to apply it to the runtime.",
    },
    {
        "id": "sec-firewalld-reload", "domain": "3.0 Security", "topic": "firewalld",
        "prompt": "Apply the permanent firewalld rules you just added to the running "
                  "(runtime) configuration.",
        "accept": ["firewall-cmd --reload"],
        "hints": ["Permanent rules aren't live until reloaded.",
                  "firewall-cmd --reload",
                  "firewall-cmd --reload"],
        "explain": "`firewall-cmd --reload` loads permanent rules into the runtime "
                   "without dropping active connections.",
    },
    {
        "id": "sec-ufw-allow", "domain": "3.0 Security", "topic": "ufw",
        "prompt": "On an Ubuntu host using ufw, allow inbound SSH (port 22/tcp).",
        "accept": ["ufw allow 22/tcp", "ufw allow ssh"],
        "hints": ["Uncomplicated FireWall: ufw.",
                  "ufw allow <port>/<proto> (or the service name).",
                  "ufw allow 22/tcp"],
        "explain": "`ufw allow 22/tcp` (or `ufw allow ssh`) permits SSH. Enable the "
                   "firewall with `ufw enable`; review with `ufw status`.",
    },
    {
        "id": "sec-sshkeygen", "domain": "3.0 Security", "topic": "SSH",
        "prompt": "Generate a new SSH key pair to use for key-based authentication.",
        "accept": ["ssh-keygen"],
        "hints": ["The tool generates a public/private key pair.",
                  "ssh-keygen (optionally -t ed25519).",
                  "ssh-keygen"],
        "explain": "`ssh-keygen` creates a key pair (default in ~/.ssh). Copy the public "
                   "key to a server with `ssh-copy-id user@host`.",
    },
    {
        "id": "sec-find-suid", "domain": "3.0 Security", "topic": "Hardening",
        "prompt": "Search the whole filesystem for files that have the SUID bit set "
                  "(a common hardening audit).",
        "accept": ["find / -perm -4000", "find / -type f -perm -4000",
                   "find / -perm /4000"],
        "hints": ["SUID is octal 4000.",
                  "Use find with -perm and the 4000 bit.",
                  "find / -perm -4000"],
        "explain": "`find / -perm -4000` lists SUID files. These run as the file owner "
                   "(often root), so unexpected ones are a security risk worth auditing.",
    },
    {
        "id": "sec-visudo", "domain": "3.0 Security", "topic": "Privilege escalation",
        "prompt": "Safely edit the sudoers configuration with syntax checking on save.",
        "accept": ["visudo"],
        "hints": ["Never edit /etc/sudoers directly.",
                  "There's a dedicated, syntax-checking editor.",
                  "visudo"],
        "explain": "`visudo` locks and syntax-checks /etc/sudoers before saving - a "
                   "typo there can lock everyone out of sudo, so always use visudo.",
    },

    # --------- 4.0 AUTOMATION, ORCHESTRATION, AND SCRIPTING ---------------- #
    {
        "id": "auto-shebang", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Scripting",
        "prompt": "Write the interpreter directive (first line) that tells the system "
                  "to run a script with the Bash shell.",
        "accept": ["#!/bin/bash", "#!/usr/bin/env bash"],
        "mode": "exact",
        "hints": ["It's called the shebang and is the script's very first line.",
                  "It starts with #! followed by the interpreter path.",
                  "#!/bin/bash"],
        "explain": "The shebang `#!/bin/bash` tells the kernel which interpreter runs "
                   "the script. `#!/usr/bin/env bash` finds bash via PATH (more portable).",
    },
    {
        "id": "auto-numeq", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Scripting",
        "prompt": "Inside a bash `test`/`[ ]`, which operator tests whether two numbers "
                  "are equal? (Type just the operator.)",
        "accept": ["-eq"],
        "mode": "exact",
        "hints": ["Numeric comparisons use lettered operators, not symbols.",
                  "EQual -> -eq (others: -ne -gt -lt -ge -le).",
                  "-eq"],
        "explain": "Bash numeric tests use `-eq -ne -lt -le -gt -ge`. The symbols "
                   "`== < >` are for STRING comparisons inside `[[ ]]`.",
    },
    {
        "id": "auto-exitcode", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Scripting",
        "prompt": "Which special variable holds the exit/return code of the command "
                  "that just ran? (Type it as you'd reference it.)",
        "accept": ["$?"],
        "mode": "exact",
        "hints": ["It's a special parameter, referenced with a $.",
                  "$ followed by a question mark.",
                  "$?"],
        "explain": "`$?` is the exit status of the last command: 0 = success, non-zero "
                   "= failure. Essential for `if` checks in scripts.",
    },
    {
        "id": "auto-ansible-playbook", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Ansible",
        "prompt": "Run the Ansible playbook defined in site.yml against your inventory.",
        "accept": ["ansible-playbook site.yml"],
        "hints": ["Ad-hoc tasks use `ansible`; full playbooks use a different command.",
                  "ansible-playbook <file>.yml",
                  "ansible-playbook site.yml"],
        "explain": "`ansible-playbook site.yml` runs a playbook. The ad-hoc `ansible "
                   "all -m ping` instead runs a single module against hosts.",
    },
    {
        "id": "auto-ansible-ping", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Ansible",
        "prompt": "Use an Ansible ad-hoc command to verify connectivity to all hosts in "
                  "the inventory with the ping module.",
        "accept": ["ansible all -m ping"],
        "hints": ["Ad-hoc commands use the `ansible` binary with -m for a module.",
                  "Target 'all', module 'ping'.",
                  "ansible all -m ping"],
        "explain": "`ansible all -m ping` runs the ping module against every inventory "
                   "host - a quick reachability/auth test (it's an Ansible ping, not ICMP).",
    },
    {
        "id": "auto-git-commit", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Version control",
        "prompt": "Commit your staged changes with the message 'fix deploy script' in "
                  "one command.",
        "accept": ["git commit -m 'fix deploy script'",
                   'git commit -m "fix deploy script"'],
        "mode": "contains",
        "hints": ["The -m flag supplies the message inline.",
                  "git commit -m 'message'",
                  "git commit -m 'fix deploy script'"],
        "explain": "`git commit -m '...'` records staged changes with a message. Stage "
                   "first with `git add`; push with `git push`.",
    },
    {
        "id": "auto-kubectl-apply", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Kubernetes",
        "prompt": "Create or update Kubernetes resources defined in the manifest "
                  "deploy.yaml.",
        "accept": ["kubectl apply -f deploy.yaml", "kubectl apply --filename deploy.yaml"],
        "hints": ["The declarative verb is `apply`; -f points at the file.",
                  "kubectl apply -f <file>",
                  "kubectl apply -f deploy.yaml"],
        "explain": "`kubectl apply -f deploy.yaml` applies a manifest declaratively "
                   "(creating or updating). `kubectl get pods` then shows the result.",
    },
    {
        "id": "auto-kubectl-scale", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Kubernetes",
        "prompt": "Scale the Kubernetes deployment named 'web' to 3 replicas.",
        "accept": ["kubectl scale deployment web --replicas=3",
                   "kubectl scale deployment/web --replicas=3",
                   "kubectl scale --replicas=3 deployment web"],
        "hints": ["The verb is `scale`; the count goes in --replicas.",
                  "kubectl scale deployment <name> --replicas=N",
                  "kubectl scale deployment web --replicas=3"],
        "explain": "`kubectl scale deployment web --replicas=3` sets the desired pod "
                   "count to 3 and Kubernetes reconciles toward it.",
    },
    {
        "id": "auto-compose-up", "domain": "4.0 Automation, Orchestration, Scripting",
        "topic": "Compose",
        "prompt": "Start all services defined in a docker-compose.yml in detached "
                  "(background) mode.",
        "accept": ["docker compose up -d", "docker-compose up -d",
                   "podman-compose up -d"],
        "hints": ["The Compose verb to start everything is `up`.",
                  "Add -d to detach.",
                  "docker compose up -d"],
        "explain": "`docker compose up -d` builds/starts every service in the Compose "
                   "file in the background. `docker compose down` tears it all down.",
    },

    # ------------------------- 5.0 TROUBLESHOOTING ------------------------- #
    {
        "id": "ts-free", "domain": "5.0 Troubleshooting", "topic": "Memory",
        "prompt": "Show total, used, and free RAM and swap in human-readable units.",
        "accept": ["free -h"],
        "hints": ["The memory summary tool is `free`.",
                  "Add -h for human-readable units.",
                  "free -h"],
        "explain": "`free -h` summarizes RAM/swap. Watch the 'available' column and "
                   "swap usage - heavy swapping signals memory pressure.",
    },
    {
        "id": "ts-vmstat", "domain": "5.0 Troubleshooting", "topic": "Performance",
        "prompt": "Report system-wide virtual memory, CPU, and I/O statistics, "
                  "refreshing every 2 seconds.",
        "accept": ["vmstat 2", "vmstat 2 ", "vmstat -w 2"],
        "hints": ["Virtual Memory STATistics.",
                  "Pass an interval in seconds as an argument: vmstat 2.",
                  "vmstat 2"],
        "explain": "`vmstat 2` refreshes every 2s. High `si/so` = swapping; high `wa` "
                   "in CPU columns = processes blocked on I/O.",
    },
    {
        "id": "ts-iostat", "domain": "5.0 Troubleshooting", "topic": "Disk I/O",
        "prompt": "Report per-device disk I/O statistics with extended details.",
        "accept": ["iostat -x", "iostat -xz"],
        "hints": ["Input/Output STATistics: iostat.",
                  "-x adds the extended per-device columns.",
                  "iostat -x"],
        "explain": "`iostat -x` shows per-device utilization and await (latency). A "
                   "%util near 100 with high await means the disk is the bottleneck.",
    },
    {
        "id": "ts-ss-listen", "domain": "5.0 Troubleshooting", "topic": "Network",
        "prompt": "List all listening TCP and UDP sockets with the owning process and "
                  "numeric ports.",
        "accept": ["ss -tulpn", "ss -tulnp", "ss -plnut", "ss -tlunp"],
        "hints": ["The modern replacement for netstat is `ss`.",
                  "t=TCP, u=UDP, l=listening, p=process, n=numeric.",
                  "ss -tulpn"],
        "explain": "`ss -tulpn`: TCP+UDP listening sockets, numeric, with PID. Flag "
                   "order doesn't matter. This is the go-to 'what's listening?' command.",
    },
    {
        "id": "ts-ip-addr", "domain": "5.0 Troubleshooting", "topic": "Network",
        "prompt": "Display the IP addresses assigned to all network interfaces.",
        "accept": ["ip a", "ip addr", "ip address", "ip -br a", "ip addr show"],
        "hints": ["`ifconfig` is deprecated; use the `ip` suite.",
                  "ip addr  (or just `ip a`).",
                  "ip a"],
        "explain": "`ip a` lists interfaces and their addresses. `ip route` shows the "
                   "routing table; `ip link` shows interface up/down state.",
    },
    {
        "id": "ts-ip-route", "domain": "5.0 Troubleshooting", "topic": "Network",
        "prompt": "Show the kernel routing table, including the default gateway.",
        "accept": ["ip route", "ip r", "ip route show"],
        "hints": ["Same `ip` suite, different object.",
                  "ip route  (or `ip r`).",
                  "ip route"],
        "explain": "`ip route` displays routes; the `default via <gw>` line is your "
                   "gateway. Missing default route = no internet beyond the LAN.",
    },
    {
        "id": "ts-dig", "domain": "5.0 Troubleshooting", "topic": "DNS",
        "prompt": "Perform a DNS lookup for the name 'example.com' to test name "
                  "resolution.",
        "accept": ["dig example.com", "nslookup example.com", "host example.com"],
        "hints": ["Several tools resolve names: dig, nslookup, host.",
                  "dig example.com",
                  "dig example.com"],
        "explain": "`dig example.com` queries DNS and shows the answer section/TTLs. "
                   "`dig +short` trims output; `dig @8.8.8.8 ...` targets a server.",
    },
    {
        "id": "ts-tcpdump", "domain": "5.0 Troubleshooting", "topic": "Network",
        "prompt": "Capture network packets live on interface eth0.",
        "accept": ["tcpdump -i eth0"],
        "hints": ["The packet capture tool is tcpdump.",
                  "-i selects the interface.",
                  "tcpdump -i eth0"],
        "explain": "`tcpdump -i eth0` captures on one interface. Add filters like "
                   "`port 80` or `host 10.0.0.5`; -w file.pcap saves for Wireshark.",
    },
    {
        "id": "ts-mtr", "domain": "5.0 Troubleshooting", "topic": "Network",
        "prompt": "Run a continuous, combined traceroute + ping to 8.8.8.8 to spot "
                  "where latency or packet loss starts.",
        "accept": ["mtr 8.8.8.8", "mtr -rw 8.8.8.8"],
        "hints": ["It blends traceroute and ping into a live report.",
                  "The tool is `mtr`.",
                  "mtr 8.8.8.8"],
        "explain": "`mtr` continuously probes each hop, showing per-hop loss and "
                   "latency - far better than a one-shot traceroute for intermittent issues.",
    },
    {
        "id": "ts-journal-priority", "domain": "5.0 Troubleshooting", "topic": "Logs",
        "prompt": "Show only error-priority (and worse) messages from the system "
                  "journal.",
        "accept": ["journalctl -p err", "journalctl -p 3", "journalctl -p error"],
        "hints": ["-p filters by priority.",
                  "Error priority is 'err' (level 3).",
                  "journalctl -p err"],
        "explain": "`journalctl -p err` shows priority err(3) and above. Levels run "
                   "0 emerg -> 7 debug; -p err is a fast triage filter.",
    },
    {
        "id": "ts-systemd-blame", "domain": "5.0 Troubleshooting", "topic": "Boot",
        "prompt": "The system boots slowly. List each systemd unit by how long it took "
                  "to initialize, slowest first.",
        "accept": ["systemd-analyze blame"],
        "hints": ["systemd-analyze has a subcommand that 'blames' slow units.",
                  "systemd-analyze blame",
                  "systemd-analyze blame"],
        "explain": "`systemd-analyze blame` ranks units by startup time. "
                   "`systemd-analyze critical-chain` shows the dependency path that "
                   "actually delayed boot.",
    },
    {
        "id": "ts-lastb", "domain": "5.0 Troubleshooting", "topic": "Security",
        "prompt": "List recent FAILED login attempts on the system.",
        "accept": ["lastb"],
        "hints": ["`last` shows successful logins; there's a sibling for bad ones.",
                  "lastb (reads /var/log/btmp).",
                  "lastb"],
        "explain": "`lastb` reads /var/log/btmp to show failed logins - useful for "
                   "spotting brute-force attempts. `last` shows successful sessions.",
    },
    {
        "id": "ts-uptime", "domain": "5.0 Troubleshooting", "topic": "Performance",
        "prompt": "Quickly check the system load averages for the last 1, 5, and 15 "
                  "minutes.",
        "accept": ["uptime", "cat /proc/loadavg"],
        "hints": ["One short command shows uptime plus three load figures.",
                  "uptime",
                  "uptime"],
        "explain": "`uptime` prints the 1/5/15-minute load averages. Compare against "
                   "your CPU core count: load well above core count = saturation.",
    },

    # ------------------ FILES & NAVIGATION (2.1) --------------------------- #
    {"id": "files-cp", "domain": "1.0 System Management", "topic": "Files",
     "prompt": "Copy the directory 'config' and everything inside it to 'config.bak'.",
     "accept": ["cp -r config config.bak", "cp -R config config.bak",
                "cp -a config config.bak"],
     "hints": ["Plain cp refuses directories.", "Recursive flag.",
               "cp -r config config.bak"],
     "explain": "`cp -r` copies directories recursively; -a additionally preserves "
                "permissions, times, and links (archive)."},
    {"id": "files-rm", "domain": "1.0 System Management", "topic": "Files",
     "prompt": "Delete the directory 'builddir' and all of its contents, without "
               "any confirmation prompts.",
     "accept": ["rm -rf builddir", "rm -fr builddir", "rm -r -f builddir"],
     "hints": ["Recursive plus force.", "-r descends, -f skips prompts.",
               "rm -rf builddir"],
     "explain": "`rm -rf` recursively force-deletes. THE classic dangerous command - "
                "exactly why we practice it here, where nothing executes."},
    {"id": "files-mkdir", "domain": "1.0 System Management", "topic": "Files",
     "prompt": "Create the nested directory path /tmp/a/b/c in one command, creating "
               "missing parents as needed.",
     "accept": ["mkdir -p /tmp/a/b/c"],
     "hints": ["Without a flag, mkdir fails if /tmp/a doesn't exist.",
               "p for parents.", "mkdir -p /tmp/a/b/c"],
     "explain": "`mkdir -p` creates every missing parent directory along the path."},
    {"id": "files-ln", "domain": "1.0 System Management", "topic": "Files",
     "prompt": "Create a symbolic link named 'webroot' pointing to /var/www/html.",
     "accept": ["ln -s /var/www/html webroot"],
     "hints": ["Without -s you get a HARD link.", "ln -s <target> <linkname>",
               "ln -s /var/www/html webroot"],
     "explain": "`ln -s target link` makes a symlink. Order trap: target FIRST."},

    # ----------------------- TEXT TOOLS (1.5) ------------------------------ #
    {"id": "text-head", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Show only the first 20 lines of boot.log.",
     "accept": ["head -n 20 boot.log", "head -20 boot.log", "head -n20 boot.log"],
     "hints": ["The opposite of tail.", "-n sets the line count.",
               "head -n 20 boot.log"],
     "explain": "`head -n N` prints the first N lines (default 10)."},
    {"id": "text-tailf", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Watch /var/log/syslog live as new lines are appended.",
     "accept": ["tail -f /var/log/syslog", "tail -F /var/log/syslog"],
     "hints": ["tail, but following.", "f for follow.", "tail -f /var/log/syslog"],
     "explain": "`tail -f` streams new lines; -F also survives log rotation."},
    {"id": "text-cut", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Print only the usernames (first field) from /etc/passwd, which is "
               "colon-delimited.",
     "accept": ["cut -d: -f1 /etc/passwd", "cut -f1 -d: /etc/passwd",
                "cut -d : -f 1 /etc/passwd"],
     "hints": ["-d sets the delimiter, -f picks the field.",
               "Delimiter is ':' and you want field 1.",
               "cut -d: -f1 /etc/passwd"],
     "explain": "`cut -d: -f1` splits on ':' and keeps field 1 - the username."},
    {"id": "text-wc", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Count how many LINES are in access.log.",
     "accept": ["wc -l access.log"],
     "hints": ["word count, but for lines.", "l for lines.", "wc -l access.log"],
     "explain": "`wc -l` counts lines; -w words, -c bytes."},
    {"id": "text-tee", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Run ./deploy.sh so its output shows on screen AND is saved to "
               "deploy.log at the same time.",
     "accept": ["./deploy.sh | tee deploy.log"], "mode": "contains",
     "hints": ["A T-shaped pipe fitting: one stream, two destinations.",
               "Pipe into tee.", "./deploy.sh | tee deploy.log"],
     "explain": "`tee` duplicates stdin to the screen and a file; -a appends."},
    {"id": "text-xargs", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Delete every file listed (one per line) in oldfiles.txt, feeding the "
               "names to rm.",
     "accept": ["xargs rm < oldfiles.txt", "cat oldfiles.txt | xargs rm"],
     "mode": "contains",
     "hints": ["rm can't read a list from stdin by itself.",
               "xargs turns stdin lines into arguments.",
               "cat oldfiles.txt | xargs rm"],
     "explain": "`xargs` converts stdin into command arguments - the glue between "
                "pipes and commands that only take args."},
    {"id": "text-sed", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Print site.conf with every occurrence of 'http' replaced by 'https'.",
     "accept": ["sed 's/http/https/g' site.conf",
                'sed "s/http/https/g" site.conf',
                "sed s/http/https/g site.conf"],
     "hints": ["The stream editor's substitute command.",
               "s/old/new/g - g means every occurrence on a line.",
               "sed 's/http/https/g' site.conf"],
     "explain": "`sed 's/old/new/g'` substitutes globally per line. Add -i to edit "
                "the file in place."},
    {"id": "text-awk", "domain": "1.0 System Management", "topic": "Text tools",
     "prompt": "Print only the first column (the client IP) of access.log using awk.",
     "accept": ["awk '{print $1}' access.log", 'awk "{print $1}" access.log'],
     "hints": ["awk splits each line into $1, $2, ...",
               "The action goes in braces: {print $1}",
               "awk '{print $1}' access.log"],
     "explain": "`awk '{print $1}'` prints field 1 of each line (whitespace-split). "
                "-F: changes the delimiter."},

    # ----------------------- PROCESSES (2.3 / 5.5) ------------------------- #

    # ----------------------- NETWORK TOOLS (1.4) --------------------------- #
    {"id": "net-ping", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Send exactly 4 ICMP echo requests to 8.8.8.8, then stop.",
     "accept": ["ping -c 4 8.8.8.8", "ping -c4 8.8.8.8"],
     "hints": ["Without a flag, ping runs forever on Linux.", "c for count.",
               "ping -c 4 8.8.8.8"],
     "explain": "`ping -c N` stops after N probes - script-friendly connectivity test."},
    {"id": "net-traceroute", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Show every router hop on the path to 8.8.8.8.",
     "accept": ["traceroute 8.8.8.8", "tracepath 8.8.8.8"],
     "hints": ["Trace the route.", "traceroute or tracepath.", "traceroute 8.8.8.8"],
     "explain": "`traceroute` maps each hop with latency; tracepath needs no root. "
                "mtr does this continuously."},
    {"id": "net-nmap", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Scan the host 10.0.0.5 for open ports.",
     "accept": ["nmap 10.0.0.5"],
     "hints": ["The network mapper.", "Just tool + host for a default scan.",
               "nmap 10.0.0.5"],
     "explain": "`nmap <host>` scans the most common ports. -p- scans all 65535."},
    {"id": "net-nc", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Test whether TCP port 22 on web01 is reachable, verbosely, without "
               "sending data (scan-only).",
     "accept": ["nc -vz web01 22", "nc -zv web01 22"],
     "hints": ["netcat can probe a single port.", "-z scan only, -v verbose.",
               "nc -vz web01 22"],
     "explain": "`nc -vz host port` reports open/refused - the quickest single-port "
                "reachability check."},
    {"id": "net-curl", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Fetch ONLY the HTTP response headers from https://example.com.",
     "accept": ["curl -I https://example.com", "curl -I https://example.com/"],
     "hints": ["You want the headers, not the body.", "Capital i.",
               "curl -I https://example.com"],
     "explain": "`curl -I` sends a HEAD request - status code and headers only."},
    {"id": "net-nmcli", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Using NetworkManager's CLI, show the status of all network devices.",
     "accept": ["nmcli device status", "nmcli dev status", "nmcli device"],
     "hints": ["NetworkManager CLI.", "Object 'device', action 'status'.",
               "nmcli device status"],
     "explain": "`nmcli device status` lists devices, types, states, and their "
                "active connection profiles."},
    {"id": "net-netplan", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Test your new netplan configuration with an automatic rollback if "
               "you don't confirm it (so a bad config can't lock you out).",
     "accept": ["netplan try"],
     "hints": ["Ubuntu's network config tool.",
               "Not 'apply' - the safer one that reverts.", "netplan try"],
     "explain": "`netplan try` applies the config and reverts unless confirmed - use "
                "it for remote machines. `netplan apply` commits immediately."},
    {"id": "net-ethtool", "domain": "1.0 System Management", "topic": "Network",
     "prompt": "Show link status, speed, and duplex settings for the NIC eth0.",
     "accept": ["ethtool eth0"],
     "hints": ["The NIC settings tool.", "Tool + interface.", "ethtool eth0"],
     "explain": "`ethtool eth0` shows negotiated speed/duplex and link detection - "
                "first stop for link-negotiation issues."},

    # --------------------- PARTITIONS & STORAGE (1.3) ---------------------- #
    {"id": "stor-blkid", "domain": "1.0 System Management", "topic": "Partitions",
     "prompt": "Show the UUID and filesystem type of every block device (for "
               "building /etc/fstab entries).",
     "accept": ["blkid"],
     "hints": ["Block id.", "No flags needed.", "blkid"],
     "explain": "`blkid` prints UUIDs and fs types - fstab's UUID= values come "
                "from here (lsblk -f shows similar)."},
    {"id": "stor-fdisk", "domain": "1.0 System Management", "topic": "Partitions",
     "prompt": "List the partition tables of all disks (read-only, no changes).",
     "accept": ["fdisk -l", "fdisk --list"],
     "hints": ["The classic partitioner has a list flag.", "l for list.",
               "fdisk -l"],
     "explain": "`fdisk -l` prints partition tables without entering interactive "
                "mode. gdisk handles GPT; parted does both."},
    {"id": "stor-parted", "domain": "1.0 System Management", "topic": "Partitions",
     "prompt": "Using parted, list all disks and their partition layouts.",
     "accept": ["parted -l", "parted --list"],
     "hints": ["Same idea as fdisk -l.", "parted with the list flag.", "parted -l"],
     "explain": "`parted -l` shows every disk's label type (gpt/msdos) and "
                "partitions - works for both MBR and GPT."},
    {"id": "fs-umount", "domain": "1.0 System Management", "topic": "Mounting",
     "prompt": "Detach the filesystem mounted at /mnt/data.",
     "accept": ["umount /mnt/data"],
     "hints": ["Watch the spelling - there's no 'n' after u.",
               "umount <mountpoint>", "umount /mnt/data"],
     "explain": "`umount` (not unmount!) detaches. 'target is busy' means a process "
                "holds files open - find it with lsof /mnt/data."},

    # ---------------------- SYSTEM SETTINGS (2.5) -------------------------- #
    {"id": "sys-timedatectl", "domain": "2.0 Services and User Management",
     "topic": "System settings",
     "prompt": "Check the system clock, timezone, and whether NTP sync is active.",
     "accept": ["timedatectl", "timedatectl status"],
     "hints": ["A systemd ctl tool for time.", "No arguments needed.",
               "timedatectl"],
     "explain": "`timedatectl` shows local/UTC time, timezone, and NTP status. "
                "set-timezone and set-ntp change them."},
    {"id": "sys-hostnamectl", "domain": "2.0 Services and User Management",
     "topic": "System settings",
     "prompt": "Permanently set the system hostname to web01.",
     "accept": ["hostnamectl set-hostname web01",
                "hostnamectl hostname web01"],
     "hints": ["The systemd hostname tool.", "Verb: set-hostname.",
               "hostnamectl set-hostname web01"],
     "explain": "`hostnamectl set-hostname` updates the static hostname persistently "
                "(plain `hostname web01` lasts only until reboot)."},
    {"id": "sys-sysctl", "domain": "2.0 Services and User Management",
     "topic": "System settings",
     "prompt": "Enable IPv4 packet forwarding RIGHT NOW by writing the kernel "
               "parameter net.ipv4.ip_forward=1.",
     "accept": ["sysctl -w net.ipv4.ip_forward=1",
                "sysctl net.ipv4.ip_forward=1"],
     "hints": ["Kernel runtime parameters live in sysctl.", "-w writes a value.",
               "sysctl -w net.ipv4.ip_forward=1"],
     "explain": "`sysctl -w key=value` sets a kernel parameter at runtime; persist "
                "it in /etc/sysctl.conf or /etc/sysctl.d/."},

    # ------------------------ USERS & GROUPS (2.2) ------------------------- #
    {"id": "user-groupadd", "domain": "2.0 Services and User Management",
     "topic": "Users",
     "prompt": "Create a new group called 'developers'.",
     "accept": ["groupadd developers"],
     "hints": ["Like useradd, but for groups.", "groupadd <name>",
               "groupadd developers"],
     "explain": "`groupadd` creates the group; groupmod renames, groupdel removes."},
    {"id": "user-getent", "domain": "2.0 Services and User Management",
     "topic": "Users",
     "prompt": "Look up alice's passwd entry through NSS (works for local AND "
               "LDAP/SSSD users).",
     "accept": ["getent passwd alice"],
     "hints": ["grep /etc/passwd misses directory users.",
               "get entries: getent <database> <key>.", "getent passwd alice"],
     "explain": "`getent passwd alice` queries every NSS source - the right way to "
                "check accounts on systems with central auth."},
    {"id": "user-chage", "domain": "2.0 Services and User Management",
     "topic": "Users",
     "prompt": "Display alice's password aging information (last change, expiry, "
               "warning days).",
     "accept": ["chage -l alice"],
     "hints": ["CHange AGE handles password aging.", "-l lists the settings.",
               "chage -l alice"],
     "explain": "`chage -l` shows aging policy; -M sets max days, -E sets account "
                "expiry."},

    # --------------------- PERMISSIONS EXTRAS (3.1) ------------------------ #
    {"id": "perm-umask", "domain": "3.0 Security", "topic": "Permissions",
     "prompt": "Set this shell's file-creation mask so new files default to 644 and "
               "new directories to 755.",
     "accept": ["umask 022", "umask 0022"],
     "hints": ["The mask SUBTRACTS from 666/777.", "666-644 = 022.", "umask 022"],
     "explain": "`umask 022` removes group/other write: files 666-022=644, "
                "dirs 777-022=755."},
    {"id": "perm-su", "domain": "3.0 Security", "topic": "Privilege escalation",
     "prompt": "Switch to the root account WITH root's full login environment "
               "(profile, PATH, home).",
     "accept": ["su -", "su - root", "su -l", "su -l root", "su --login"],
     "hints": ["Plain su keeps YOUR environment.", "The dash makes it a login shell.",
               "su -"],
     "explain": "`su -` starts a login shell as root; without the dash you keep "
                "your own env, which breaks PATH-dependent admin tools."},
    {"id": "perm-sudoi", "domain": "3.0 Security", "topic": "Privilege escalation",
     "prompt": "Using sudo, open an interactive root login shell.",
     "accept": ["sudo -i", "sudo --login"],
     "hints": ["sudo with one flag.", "i for interactive login.", "sudo -i"],
     "explain": "`sudo -i` simulates a root login (root's env); `sudo -s` keeps "
                "your environment instead."},

    # -------------------------- SELINUX (3.1) ------------------------------ #
    {"id": "sel-semanage", "domain": "3.0 Security", "topic": "SELinux",
     "prompt": "Allow httpd to bind to the non-standard port 8081 by adding it to "
               "the http_port_t SELinux port type.",
     "accept": ["semanage port -a -t http_port_t -p tcp 8081"],
     "hints": ["semanage manages persistent policy; object here is 'port'.",
               "-a add, -t type, -p protocol.",
               "semanage port -a -t http_port_t -p tcp 8081"],
     "explain": "`semanage port -a -t http_port_t -p tcp 8081` - THE fix when a "
                "service won't bind to a custom port under SELinux."},

    # ------------------------- FIREWALLS (3.2) ----------------------------- #
    {"id": "fw-iptables", "domain": "3.0 Security", "topic": "Firewalls",
     "prompt": "List all iptables rules with packet counters and numeric "
               "addresses/ports (no DNS lookups).",
     "accept": ["iptables -L -n -v", "iptables -nvL", "iptables -vnL",
                "iptables -L -v -n"],
     "hints": ["Three flags: List, numeric, verbose.", "-L -n -v in any order.",
               "iptables -L -n -v"],
     "explain": "`iptables -L -n -v`: -n skips slow DNS, -v adds packet/byte "
                "counters - showing which rules actually match traffic."},
    {"id": "fw-nft", "domain": "3.0 Security", "topic": "Firewalls",
     "prompt": "Display the complete current nftables ruleset.",
     "accept": ["nft list ruleset"],
     "hints": ["nftables CLI is nft.", "list + the whole ruleset.",
               "nft list ruleset"],
     "explain": "`nft list ruleset` dumps all tables/chains/rules - nftables is the "
                "modern netfilter frontend that firewalld uses underneath."},

    # ------------------------ BACKUP EXTRAS (1.6) -------------------------- #
    {"id": "bk-dd", "domain": "1.0 System Management", "topic": "Backup",
     "prompt": "Create a raw image of the whole disk /dev/sda into disk.img, using "
               "4 MiB blocks, showing progress.",
     "accept": ["dd if=/dev/sda of=disk.img bs=4M status=progress",
                "dd if=/dev/sda of=disk.img status=progress bs=4M",
                "dd bs=4M if=/dev/sda of=disk.img status=progress"],
     "hints": ["if= input file, of= output file.", "bs=4M and status=progress.",
               "dd if=/dev/sda of=disk.img bs=4M status=progress"],
     "explain": "`dd if= of= bs=4M status=progress` images a device byte-for-byte. "
                "Triple-check if/of - reversed, it destroys the source."},
    {"id": "bk-bzip2", "domain": "1.0 System Management", "topic": "Compression",
     "prompt": "Compress big.log with bzip2 (better ratio than gzip, slower).",
     "accept": ["bzip2 big.log"],
     "hints": ["Same usage pattern as gzip.", "Produces .bz2.", "bzip2 big.log"],
     "explain": "`bzip2` -> .bz2; decompress with bunzip2/-d. tar's matching flag "
                "is -j."},
    {"id": "bk-xz", "domain": "1.0 System Management", "topic": "Compression",
     "prompt": "Compress big.log with xz (best ratio of the three).",
     "accept": ["xz big.log"],
     "hints": ["Same pattern again.", "Produces .xz.", "xz big.log"],
     "explain": "`xz` -> .xz; decompress with unxz/-d. tar's matching flag is -J. "
                "Ratio: xz > bzip2 > gzip; speed is the reverse."},

    # ------------------------ PACKAGES EXTRAS (2.4) ------------------------ #
    {"id": "sw-dpkg", "domain": "2.0 Services and User Management",
     "topic": "Software",
     "prompt": "Install the local Debian package file ./agent.deb directly (no "
               "repository).",
     "accept": ["dpkg -i agent.deb", "dpkg -i ./agent.deb",
                "apt install ./agent.deb"],
     "hints": ["apt talks to repos; local .deb files use the lower-level tool.",
               "dpkg with -i.", "dpkg -i agent.deb"],
     "explain": "`dpkg -i file.deb` installs a local package (deps NOT auto-resolved; "
                "`apt install ./file.deb` does resolve them)."},
    {"id": "sw-rpmqa", "domain": "2.0 Services and User Management",
     "topic": "Software",
     "prompt": "On a RHEL-family system, list EVERY installed package.",
     "accept": ["rpm -qa", "dnf list installed", "yum list installed"],
     "hints": ["rpm query, all.", "rpm -qa", "rpm -qa"],
     "explain": "`rpm -qa` queries all installed packages; pipe to grep to find one. "
                "-qi shows info, -ql lists a package's files."},
    {"id": "sw-pip", "domain": "2.0 Services and User Management",
     "topic": "Software",
     "prompt": "Install the Python package 'requests' with pip.",
     "accept": ["pip install requests", "pip3 install requests"],
     "hints": ["Python's package installer.", "pip install <pkg>",
               "pip install requests"],
     "explain": "`pip install` pulls from PyPI - language-level packages, separate "
                "from apt/dnf system packages."},
]


# --------------------------------------------------------------------------- #
#  Tutorial briefings  (used only in Tutorial difficulty)
#  keyed by scenario id ->  why | flags [[flag, meaning], ...] | target |
#                           tool_label (override the auto-detected tool name)
#  Scenarios without an entry still work in Tutorial mode: the brief falls
#  back to the scenario's explanation plus any flags found in the answer.
# --------------------------------------------------------------------------- #

TEACH = {
    # ---- 1.0 ----
    "proc-ps": {"why": "ps takes a one-time snapshot of the process table.",
        "flags": [["a", "(BSD) processes of all users"],
                  ["u", "(BSD) user-oriented detail: owner, %CPU, %MEM"],
                  ["x", "(BSD) include processes with no controlling tty"],
                  ["-e", "(System V) every process"],
                  ["-f", "(System V) full-format listing"]],
        "target": "every process on the system"},
    "proc-kill9": {"why": "kill sends a signal to a process by PID.",
        "flags": [["-9 / -KILL", "SIGKILL: force kill, cannot be caught"],
                  ["-15 / -TERM", "SIGTERM: polite stop (the default)"],
                  ["-s SIG", "choose the signal by name or number"]],
        "target": "the stuck PID 4821"},
    "proc-killall": {"why": "killall signals processes by NAME, not PID.",
        "flags": [["(name)", "sends SIGTERM by default"],
                  ["-9", "force with SIGKILL"],
                  ["-i", "ask for confirmation on each match"]],
        "target": "every process named nginx"},
    "proc-renice": {"why": "renice changes the niceness of an ALREADY running process (nice does it at launch).",
        "flags": [["N", "the new nice value (-20 highest .. 19 lowest priority)"],
                  ["-n N", "same, stated explicitly"],
                  ["-p PID", "target a PID (the default)"],
                  ["-u USER", "target all of a user's processes"]],
        "target": "running PID 2000, set to nice 10"},
    "proc-lsof-port": {"why": "lsof lists open files; sockets count as files, so it can map a port to a process.",
        "flags": [["-i", "internet (network) connections"],
                  ["-i :PORT", "a specific port"],
                  ["-p PID", "files opened by a PID"]],
        "target": "whatever is on TCP port 80"},
    "proc-nohup": {"why": "Closing a shell sends SIGHUP to its children; nohup makes a job ignore it, and trailing & backgrounds it.",
        "target": "./backup.sh, kept alive after logout"},
    "sched-crontab-edit": {"why": "crontab manages a user's scheduled jobs.",
        "flags": [["-e", "edit the crontab"], ["-l", "list it"],
                  ["-r", "remove it"], ["-u USER", "act on another user's crontab"]]},
    "dev-modprobe": {"why": "modprobe loads a kernel module AND its dependencies (insmod ignores deps).",
        "flags": [["(name)", "load the module + dependencies"],
                  ["-r", "remove a module"], ["-v", "verbose"]],
        "target": "the vfio module"},
    "dev-modprobe-r": {"why": "modprobe -r (or rmmod) unloads a module.",
        "flags": [["-r", "remove the module + unused deps"],
                  ["rmmod", "remove just the one module"]],
        "target": "the loaded pcspkr module"},
    "dev-modinfo": {"why": "modinfo prints a module's metadata even when it isn't loaded.",
        "flags": [["-p", "parameters only"], ["-d", "description"],
                  ["-l", "license"]], "target": "the e1000e module"},
    "dev-dracut": {"why": "dracut builds the initramfs (the early-boot image of drivers/modules).",
        "flags": [["-f / --force", "overwrite the existing image"],
                  ["--kver V", "build for a specific kernel version"],
                  ["-v", "verbose"]],
        "target": "the current kernel's initramfs (Debian: update-initramfs -u)"},
    "dev-lsblk": {"why": "lsblk shows block devices as a tree.",
        "flags": [["-f", "show filesystems/UUIDs"], ["-p", "full device paths"],
                  ["-o COLS", "choose columns"]]},
    "dev-dmesg": {"why": "dmesg prints the kernel ring buffer (hardware/driver messages).",
        "flags": [["-T", "human-readable timestamps"], ["-w", "follow/wait for new"],
                  ["-l err", "filter by level"]]},
    "lvm-pvcreate": {"why": "LVM stacks: physical volume -> volume group -> logical volume. pvcreate makes step 1.",
        "target": "the new disk /dev/sdb"},
    "lvm-vgcreate": {"why": "vgcreate pools one or more PVs into a named volume group.",
        "flags": [["<vgname> <pv...>", "name first, then the physical volume(s)"]],
        "target": "VG 'datavg' built on /dev/sdb"},
    "lvm-lvcreate": {"why": "lvcreate carves a logical volume out of a volume group.",
        "flags": [["-L SIZE", "fixed size, e.g. 20G"],
                  ["-l 100%FREE", "by extents/percentage instead"],
                  ["-n NAME", "name the logical volume"]],
        "target": "20G LV 'web' from VG 'datavg'"},
    "lvm-lvextend": {"why": "lvextend grows an LV; with -r it grows the filesystem in the same step.",
        "flags": [["-L +SIZE", "ADD to current size (+5G)"],
                  ["-l +100%FREE", "use all free extents"],
                  ["-r / --resizefs", "resize the filesystem too"]],
        "target": "/dev/datavg/web, +5G"},
    "fs-resize2fs": {"why": "resize2fs grows (or shrinks, when unmounted) ext2/3/4 filesystems.",
        "target": "the ext4 fs on /dev/datavg/web"},
    "fs-xfsgrow": {"why": "xfs_growfs grows a MOUNTED XFS filesystem (XFS only grows, never shrinks).",
        "flags": [["<mountpoint>", "note: takes the mount point, not the device"]],
        "target": "the XFS mounted at /data"},
    "fs-mkfs": {"why": "mkfs writes a fresh filesystem onto a partition (this erases it!).",
        "flags": [["mkfs.TYPE", "e.g. mkfs.ext4, mkfs.xfs"],
                  ["-t TYPE", "alternative: mkfs -t ext4"],
                  ["-L LABEL", "set a filesystem label"]],
        "target": "/dev/sdc1 as ext4"},
    "fs-mount-opts": {"why": "mount attaches a device into the directory tree; -o passes options.",
        "flags": [["-o ro", "read-only"], ["-r", "read-only shortcut"],
                  ["-o noexec,nosuid", "common hardening options"],
                  ["-t TYPE", "force a filesystem type"]],
        "target": "/dev/sdc1 at /mnt/data, read-only"},
    "fs-df": {"why": "df reports free/used space per mounted filesystem.",
        "flags": [["-h", "human units (1024-based)"], ["-H", "SI units (1000-based)"],
                  ["-T", "show filesystem type"], ["-i", "show inodes instead"]]},
    "fs-du": {"why": "du estimates how much space files/dirs occupy.",
        "flags": [["-s", "summarize: one total"], ["-h", "human-readable"],
                  ["-a", "include individual files"], ["--max-depth=N", "limit depth"]],
        "target": "the /var/log directory"},
    "fs-fsck": {"why": "fsck checks/repairs a filesystem; the device MUST be unmounted.",
        "flags": [["-y", "answer yes to all repairs"], ["-n", "check only, no changes"],
                  ["-f", "force even if marked clean"]], "target": "unmounted /dev/sdc1"},
    "shell-grep": {"why": "grep searches text for a pattern.",
        "flags": [["-r / -R", "recurse into directories"], ["-i", "ignore case"],
                  ["-n", "show line numbers"], ["-l", "list matching filenames only"],
                  ["-v", "invert: lines that DON'T match"], ["-E", "extended regex"]],
        "target": "the word 'error' under /var/log, case-insensitive"},
    "shell-find-size": {"why": "find walks the tree and filters by tests like size, name, time.",
        "flags": [["-size +N[kMG]", "larger than N (e.g. +100M)"],
                  ["-type f", "regular files only"], ["-name PAT", "match by name"],
                  ["-mtime N", "by modification age in days"]],
        "target": "files over 100 MB, starting at /"},
    "shell-stderr": {"tool_label": "redirection (2>)",
        "why": "Each stream has a file descriptor: 1 = stdout, 2 = stderr.",
        "flags": [["2> file", "send ONLY stderr to file"],
                  ["> file", "send stdout"], ["2>&1", "merge stderr into stdout"],
                  ["&> file", "send BOTH to one file"]],
        "target": "stderr of ./build.sh into errors.log"},
    "shell-sort-uniq": {"tool_label": "sort | uniq",
        "why": "uniq only collapses ADJACENT duplicate lines, so you sort first, then pipe.",
        "flags": [["sort", "order the lines"], ["uniq -c", "collapse + prefix a count"],
                  ["uniq -d", "show only duplicated lines"]],
        "target": "count of each unique line in access.log"},
    "backup-tar-create": {"why": "tar bundles files into one archive, optionally compressed.",
        "flags": [["-c", "create"], ["-x", "extract"], ["-z", "gzip"],
                  ["-j", "bzip2"], ["-v", "verbose"],
                  ["-f FILE", "the archive file (name comes right after f)"]],
        "target": "gzip archive backup.tar.gz of /etc"},
    "backup-tar-extract": {"why": "Same tar, swap create for extract.",
        "flags": [["-x", "extract"], ["-z", "gzip"], ["-f FILE", "the archive"],
                  ["-C DIR", "extract into a different directory"]],
        "target": "backup.tar.gz into the current directory"},
    "backup-rsync": {"why": "rsync syncs files efficiently, locally or over SSH.",
        "flags": [["-a", "archive: recursive + preserve perms/times/links"],
                  ["-v", "verbose"], ["-z", "compress during transfer"],
                  ["--delete", "mirror deletions too"], ["-n", "dry run"]],
        "target": "/home/data/ -> backup01:/srv/data (trailing / copies contents)"},
    "backup-gzip": {"why": "gzip compresses a single file in place.",
        "flags": [["(file)", "compress -> file.gz, removes original"],
                  ["-d", "decompress (= gunzip)"], ["-k", "keep the original"],
                  ["-9", "maximum compression"]], "target": "huge.log"},
    "virt-virsh-list": {"why": "virsh is the libvirt command-line client.",
        "flags": [["list", "running domains"], ["--all", "include powered-off VMs"],
                  ["start/shutdown NAME", "control a VM"]]},
    # ---- 2.0 ----
    "sd-enable-now": {"why": "systemctl controls systemd units. enable = at boot; start = now.",
        "flags": [["enable", "start automatically at boot"],
                  ["--now", "ALSO start (or stop) immediately"],
                  ["disable", "remove from boot"]],
        "target": "sshd: enable + start in one go"},
    "sd-status": {"why": "status shows a unit's active state, main PID, and recent log lines.",
        "flags": [["status UNIT", "state + last journal lines"],
                  ["is-active UNIT", "just active/inactive"]], "target": "nginx"},
    "sd-daemon-reload": {"why": "systemd caches unit files; after editing one by hand you must reload the manager's view.",
        "target": "re-read unit files (NOT the same as reloading a service)"},
    "sd-mask": {"why": "disable only stops boot-start; mask links the unit to /dev/null so it can't start at all.",
        "flags": [["mask UNIT", "make un-startable"], ["unmask UNIT", "reverse it"]],
        "target": "the bluetooth service"},
    "log-journalctl-unit": {"why": "journalctl queries the binary systemd journal.",
        "flags": [["-u UNIT", "filter by unit"], ["-b", "current boot"],
                  ["-b -1", "previous boot"], ["-p PRIO", "by priority"],
                  ["-f", "follow live"], ["-k", "kernel only"],
                  ["--since/--until", "time range"]],
        "target": "sshd, current boot"},
    "log-journalctl-follow": {"why": "Like tail -f, but for the journal.",
        "flags": [["-f / --follow", "stream new entries live"],
                  ["-n N", "start with the last N lines"]]},
    "sw-apt-install": {"why": "apt is the Debian/Ubuntu package manager front end.",
        "flags": [["update", "refresh the package index first"],
                  ["install PKG", "install"], ["remove PKG", "remove"],
                  ["upgrade", "upgrade installed packages"]], "target": "htop"},
    "sw-dnf-install": {"why": "dnf is the Red Hat/Fedora package manager (yum is its older alias).",
        "flags": [["install PKG", "install"], ["remove PKG", "remove"],
                  ["check-update", "list available updates"], ["search TERM", "find"]],
        "target": "httpd"},
    "user-useradd": {"why": "useradd creates an account; pair it with passwd to set a password.",
        "flags": [["-m", "create the home directory"], ["-s SHELL", "login shell"],
                  ["-G g1,g2", "supplementary groups"], ["-c TEXT", "comment/full name"]],
        "target": "alice, with home dir and /bin/bash"},
    "user-usermod-group": {"why": "usermod edits an existing account. The classic trap: -G alone REPLACES all groups.",
        "flags": [["-a", "APPEND (must be combined with -G)"],
                  ["-G GROUP", "supplementary group(s)"], ["-L", "lock"],
                  ["-s SHELL", "change shell"]],
        "target": "add alice to 'docker' WITHOUT dropping her other groups"},
    "user-lock": {"why": "Locking disables password login without deleting the account.",
        "flags": [["usermod -L", "lock"], ["passwd -l", "lock (alternative)"],
                  ["-U / -u", "unlock"]], "target": "the user bob"},
    "ctr-run": {"why": "run creates and starts a NEW container from an image (podman and docker share this syntax).",
        "flags": [["-d", "detached (background)"], ["-p H:C", "publish host:container port"],
                  ["-it", "interactive + TTY"], ["--name N", "name it"],
                  ["-e K=V", "environment variable"], ["-v SRC:DST", "mount a volume"]],
        "target": "nginx, background, host 8080 -> container 80"},
    "ctr-ps": {"why": "ps lists containers (running by default).",
        "flags": [["-a", "all, including stopped"], ["-q", "IDs only"]]},
    "ctr-logs": {"why": "Containers capture stdout/stderr; logs replays them.",
        "flags": [["(name)", "show the logs"], ["-f", "follow live"],
                  ["--tail N", "last N lines"]], "target": "the 'web' container"},
    "ctr-exec": {"why": "exec runs a command INSIDE an already-running container (run would start a new one).",
        "flags": [["-it", "interactive shell"], ["(name) (cmd)", "container then command"]],
        "target": "a bash shell in 'web'"},
    "ctr-build": {"why": "build turns a Dockerfile + context into an image.",
        "flags": [["-t name:tag", "tag the image"], ["-f FILE", "alternate Dockerfile"],
                  [".", "the build context (don't forget it!)"]],
        "target": "image myapp:1.0 from ./Dockerfile"},
    "ctr-prune": {"why": "prune reclaims space from unused objects.",
        "flags": [["image prune", "dangling images"],
                  ["system prune", "containers + networks + more"],
                  ["-a", "all unused, not just dangling"], ["-f", "skip confirmation"]]},
    # ---- 3.0 ----
    "sec-chmod-octal": {"why": "Octal mode: r=4, w=2, x=1, summed per column (owner/group/other).",
        "flags": [["NNN", "three octal digits, e.g. 755"], ["-R", "recurse"]],
        "target": "script.sh -> rwx r-x r-x"},
    "sec-chmod-symbolic": {"why": "Symbolic mode: who (u/g/o/a) + op (+/-/=) + perms (rwx).",
        "flags": [["u/g/o/a", "user/group/other/all"], ["+ - =", "add/remove/set"]],
        "target": "add execute for the owner of deploy.sh"},
    "sec-chown": {"why": "chown changes ownership; user:group sets both at once.",
        "flags": [["user:group", "set owner and group"], [":group", "group only"],
                  ["-R", "recurse a tree"]], "target": "report.txt -> alice:staff"},
    "sec-setfacl": {"why": "ACLs grant extra per-user/group permissions beyond owner/group/other.",
        "flags": [["-m", "modify/add an entry"], ["-x", "remove an entry"],
                  ["-b", "strip all ACLs"], ["u:USER:perms", "a user entry"],
                  ["-R", "recurse"]], "target": "give bob rw on project.txt (view with getfacl)"},
    "sec-chattr": {"why": "chattr sets low-level filesystem attributes; +i blocks all changes even by root.",
        "flags": [["+i", "immutable"], ["-i", "remove immutable"],
                  ["+a", "append-only"]], "target": "/etc/resolv.conf (check with lsattr)"},
    "sec-setenforce": {"why": "setenforce flips SELinux between enforcing and permissive at runtime.",
        "flags": [["0 / Permissive", "log denials but allow"],
                  ["1 / Enforcing", "block denials"]],
        "target": "permissive now (persist via /etc/selinux/config; check with getenforce)"},
    "sec-restorecon": {"why": "restorecon re-labels files to the contexts the SELinux policy expects.",
        "flags": [["-R", "recurse"], ["-v", "verbose"], ["-F", "force a reset"]],
        "target": "/var/www and everything under it"},
    "sec-setsebool": {"why": "Booleans toggle optional SELinux policy behaviors.",
        "flags": [["-P", "persistent: survive reboot"], ["on / off", "the value"]],
        "target": "httpd_can_network_connect, on, permanently (list with getsebool -a)"},
    "sec-firewalld-port": {"why": "firewall-cmd manages firewalld zones/rules.",
        "flags": [["--permanent", "persist (apply with --reload)"],
                  ["--add-port=P/proto", "open a port"],
                  ["--add-service=NAME", "open a known service"],
                  ["--zone=Z", "target a zone"], ["--list-all", "show config"]],
        "target": "open 443/tcp permanently"},
    "sec-firewalld-reload": {"why": "Permanent rules don't take effect until reloaded into the runtime.",
        "target": "apply the permanent rules now"},
    "sec-ufw-allow": {"why": "ufw is Ubuntu's simple firewall front end.",
        "flags": [["allow PORT/proto", "permit"], ["allow NAME", "by service name"],
                  ["deny", "block"], ["enable", "turn the firewall on"],
                  ["status", "show rules"]], "target": "inbound SSH (22/tcp)"},
    "sec-sshkeygen": {"why": "ssh-keygen creates the key pair for password-less SSH.",
        "flags": [["-t ed25519", "key type (modern default)"], ["-b BITS", "key size"],
                  ["-C TEXT", "a label/comment"], ["-f FILE", "output filename"]],
        "target": "a new key pair (then push it with ssh-copy-id)"},
    "sec-find-suid": {"why": "SUID files run as their owner (often root) - a key thing to audit.",
        "flags": [["-perm -4000", "the SUID bit is set"],
                  ["-perm -2000", "SGID"], ["-type f", "files only"]],
        "target": "all SUID files, from /"},
    "sec-visudo": {"why": "visudo locks and syntax-checks sudoers before saving, so a typo can't lock you out.",
        "target": "edit the sudoers policy safely"},
    # ---- 4.0 ----
    "auto-shebang": {"tool_label": "shebang (#!)",
        "why": "The first line names the interpreter that runs the script.",
        "flags": [["#!/bin/bash", "fixed path to bash"],
                  ["#!/usr/bin/env bash", "find bash via PATH (portable)"]]},
    "auto-numeq": {"tool_label": "bash test operators",
        "why": "Numeric tests use lettered operators; symbols (== < >) are for STRINGS.",
        "flags": [["-eq / -ne", "equal / not equal"], ["-lt / -le", "less than / or equal"],
                  ["-gt / -ge", "greater than / or equal"]]},
    "auto-exitcode": {"tool_label": "exit status",
        "why": "Every command sets a return code: 0 = success, non-zero = failure.",
        "flags": [["$?", "the last command's exit status"]]},
    "auto-ansible-playbook": {"why": "ansible-playbook runs a full YAML playbook.",
        "flags": [["FILE.yml", "the playbook"], ["-i INV", "inventory file"],
                  ["--check", "dry run"], ["--limit HOST", "subset of hosts"],
                  ["-K", "prompt for the become (sudo) password"]], "target": "site.yml"},
    "auto-ansible-ping": {"why": "Ad-hoc ansible runs a single module against hosts (no playbook).",
        "flags": [["all", "the host group/pattern"], ["-m MODULE", "the module"],
                  ["-a ARGS", "module arguments"]], "target": "ping all inventory hosts"},
    "auto-git-commit": {"why": "git records staged changes as a commit.",
        "flags": [["commit -m MSG", "commit staged files with a message"],
                  ["add FILE", "stage changes"], ["-am MSG", "stage tracked + commit"],
                  ["push", "upload to remote"]], "target": "message 'fix deploy script'"},
    "auto-kubectl-apply": {"why": "kubectl apply creates/updates resources declaratively from a manifest.",
        "flags": [["apply -f FILE", "apply a manifest"], ["get pods", "list pods"],
                  ["delete -f FILE", "remove"], ["-n NS", "namespace"]],
        "target": "deploy.yaml"},
    "auto-kubectl-scale": {"why": "scale sets the desired replica count and Kubernetes reconciles to it.",
        "flags": [["scale deployment NAME", "what to scale"],
                  ["--replicas=N", "desired pod count"]], "target": "deployment 'web' to 3"},
    "auto-compose-up": {"tool_label": "docker compose",
        "why": "Compose runs a whole multi-service app from one YAML file.",
        "flags": [["up", "create + start services"], ["-d", "detached/background"],
                  ["down", "stop + remove everything"], ["logs", "view logs"]]},
    # ---- 5.0 ----
    "ts-free": {"why": "free summarizes RAM and swap; watch 'available' and swap use.",
        "flags": [["-h", "human units"], ["-m", "MiB"], ["-g", "GiB"],
                  ["-s N", "refresh every N seconds"]]},
    "ts-vmstat": {"why": "vmstat reports memory/CPU/IO; an interval makes it sample repeatedly.",
        "flags": [["N", "seconds between samples"], ["-w", "wide output"],
                  ["-s", "one-shot summary"]],
        "target": "every 2s (read si/so for swap, wa for IO wait)"},
    "ts-iostat": {"why": "iostat shows per-device disk activity.",
        "flags": [["-x", "extended columns (%util, await)"], ["-z", "skip idle devices"],
                  ["-d", "device stats only"], ["N", "interval"]],
        "target": "per-device, extended"},
    "ts-ss-listen": {"why": "ss is the modern replacement for netstat.",
        "flags": [["-t", "TCP"], ["-u", "UDP"], ["-l", "listening only"],
                  ["-p", "show owning process"], ["-n", "numeric (skip DNS)"],
                  ["-a", "all states"]],
        "target": "listening TCP+UDP, numeric, with PIDs"},
    "ts-ip-addr": {"why": "The ip suite replaced ifconfig.",
        "flags": [["a / addr", "addresses"], ["link", "interface up/down"],
                  ["route", "routing table"], ["-br", "brief output"]],
        "target": "addresses on all interfaces"},
    "ts-ip-route": {"why": "ip route shows the routing table; the 'default via' line is your gateway.",
        "flags": [["route / r", "show routes"], ["get IP", "which route a destination uses"]]},
    "ts-dig": {"why": "dig is the detailed DNS query tool.",
        "flags": [["NAME", "query an A record"], ["+short", "trim the output"],
                  ["@SERVER", "ask a specific resolver"], ["NAME MX", "a record type"]],
        "target": "resolve example.com"},
    "ts-tcpdump": {"why": "tcpdump captures packets off the wire.",
        "flags": [["-i IFACE", "the interface"], ["-n", "numeric (no DNS)"],
                  ["-w FILE", "save a .pcap"], ["port 80 / host X", "capture filters"],
                  ["-c N", "stop after N packets"]], "target": "interface eth0"},
    "ts-mtr": {"why": "mtr blends traceroute + ping, probing every hop continuously.",
        "flags": [["HOST", "the target"], ["-r", "report mode (one batch)"],
                  ["-w", "wide report"], ["-c N", "number of cycles"]],
        "target": "8.8.8.8"},
    "ts-journal-priority": {"why": "Journal priorities run 0 emerg .. 7 debug; filter to surface problems fast.",
        "flags": [["-p err", "priority err (3) and worse"], ["-p 0..7", "any level"],
                  ["-b", "limit to this boot"]]},
    "ts-systemd-blame": {"tool_label": "systemd-analyze",
        "why": "It ranks units by how long each took to initialize at boot.",
        "flags": [["blame", "slowest units first"],
                  ["critical-chain", "the dependency path that actually delayed boot"]]},
    "ts-lastb": {"tool_label": "lastb",
        "why": "lastb reads /var/log/btmp to show FAILED logins (last shows successful ones).",
        "target": "recent failed login attempts"},
    "ts-uptime": {"why": "uptime prints the 1/5/15-minute load averages.",
        "target": "compare the averages to your CPU core count (above it = saturation)"},
}


# --------------------------------------------------------------------------- #
#  Rep drills (Tutorial mode)
#  After solving a scenario, the learner can keep hammering the SAME tool with
#  these variations until it sticks.  Keyed by tool; related commands are
#  grouped via TOOL_ALIASES (docker->podman, pv/vg/lv*->lvm, ...).
#  drill keys:  q = task   a = accepted answers   h = hint   e = explanation
#               m = match mode (optional)
# --------------------------------------------------------------------------- #

TOOL_ALIASES = {
    "docker": "podman", "killall": "kill", "pkill": "kill",
    "gunzip": "gzip", "zcat": "gzip", "zgrep": "gzip",
    "yum": "dnf", "apt-get": "apt",
    "nslookup": "dig", "host": "dig",
    "rmmod": "modprobe", "insmod": "modprobe", "lsmod": "modprobe",
    "modinfo": "modprobe", "depmod": "modprobe",
    "pvcreate": "lvm", "vgcreate": "lvm", "vgextend": "lvm",
    "lvcreate": "lvm", "lvextend": "lvm", "lvremove": "lvm",
    "pvs": "lvm", "vgs": "lvm", "lvs": "lvm",
    "umount": "mount",
    "usermod": "useradd", "userdel": "useradd", "passwd": "useradd",
    "chage": "useradd",
    "setenforce": "selinux", "restorecon": "selinux", "setsebool": "selinux",
    "getenforce": "selinux", "chcon": "selinux", "getsebool": "selinux",
    "ssh-copy-id": "ssh-keygen", "ssh": "ssh-keygen",
    "mkinitrd": "dracut", "update-initramfs": "dracut",
    "resize2fs": "fsresize", "xfs_growfs": "fsresize",
    "getfacl": "setfacl", "lsattr": "chattr", "chgrp": "chown",
    "ansible-playbook": "ansible",
    "mkfs.ext4": "mkfs", "mkfs.xfs": "mkfs",
    "#!/bin/bash": "bash-basics", "$?": "bash-basics", "-eq": "bash-basics",
    "./build.sh": "redirection", "./deploy.sh": "tee",
    "tracepath": "traceroute", "htop": "top", "w": "who", "pip3": "pip",
    "bunzip2": "bzip2", "unxz": "xz", "groupmod": "groupadd",
    "groupdel": "groupadd", "hostname": "hostnamectl",
}


def drill_key(sc):
    """Map a scenario to its drill-bank key (its tool family)."""
    toks = sc["accept"][0].split()
    if toks[0] in ("docker", "podman") and len(toks) > 1 and toks[1] == "compose":
        return "compose"
    if toks[0] == "docker-compose":
        return "compose"
    return TOOL_ALIASES.get(toks[0], toks[0])


DRILLS = {
    "journalctl": [
        {"q": "Follow the journal live (stream new entries).",
         "a": ["journalctl -f", "journalctl --follow"], "h": "Like tail -f.",
         "e": "-f follows live."},
        {"q": "Show only kernel messages from the journal.",
         "a": ["journalctl -k", "journalctl --dmesg"], "h": "k for kernel.",
         "e": "-k limits to the kernel transport (like dmesg)."},
        {"q": "Show the journal from the PREVIOUS boot.",
         "a": ["journalctl -b -1"], "h": "-b takes an offset.",
         "e": "-b -1 = one boot back; -b alone = current boot."},
        {"q": "Show entries for the nginx unit, current boot only.",
         "a": ["journalctl -u nginx -b", "journalctl -b -u nginx",
               "journalctl -u nginx.service -b"],
         "h": "-u for unit, -b for boot.", "e": "Combine -u and -b freely."},
        {"q": "Show only warning-priority messages and worse.",
         "a": ["journalctl -p warning", "journalctl -p 4", "journalctl -p warn"],
         "h": "-p takes a priority name or number.",
         "e": "warning = level 4; err = 3; crit = 2."},
        {"q": "Show just the last 50 journal lines.",
         "a": ["journalctl -n 50"], "h": "Same letter tail uses for line count.",
         "e": "-n N starts from the last N entries."},
    ],
    "systemctl": [
        {"q": "Restart the sshd service.",
         "a": ["systemctl restart sshd", "systemctl restart sshd.service"],
         "h": "The verb is restart.", "e": "restart = stop + start."},
        {"q": "Stop the nginx service (just for now).",
         "a": ["systemctl stop nginx", "systemctl stop nginx.service"],
         "h": "stop affects now; disable affects boot.",
         "e": "stop only affects the running instance."},
        {"q": "Stop the cups service from starting at boot (but allow manual starts).",
         "a": ["systemctl disable cups", "systemctl disable cups.service"],
         "h": "Not mask - it should still be startable.",
         "e": "disable removes boot-start; mask would block it entirely."},
        {"q": "Check whether httpd is set to start at boot.",
         "a": ["systemctl is-enabled httpd", "systemctl is-enabled httpd.service"],
         "h": "is-...", "e": "is-enabled prints enabled/disabled; is-active checks now."},
        {"q": "List all units that have FAILED.",
         "a": ["systemctl --failed", "systemctl list-units --failed",
               "systemctl list-units --state=failed"],
         "h": "There's a --failed shortcut.",
         "e": "A quick health check after boot or an incident."},
        {"q": "Undo a mask on the bluetooth service.",
         "a": ["systemctl unmask bluetooth", "systemctl unmask bluetooth.service"],
         "h": "The opposite of mask.", "e": "unmask removes the /dev/null link."},
        {"q": "Reload nginx's configuration without dropping connections.",
         "a": ["systemctl reload nginx", "systemctl reload nginx.service"],
         "h": "Not restart - gentler.",
         "e": "reload signals the service to re-read config; restart kills it."},
    ],
    "tar": [
        {"q": "LIST the contents of backup.tar.gz without extracting.",
         "a": ["tar -tzf backup.tar.gz", "tar tzf backup.tar.gz",
               "tar -tzvf backup.tar.gz", "tar tzvf backup.tar.gz"],
         "h": "t = table of contents.", "e": "-t lists; -x extracts."},
        {"q": "Extract site.tar.gz into /tmp instead of the current dir.",
         "a": ["tar -xzf site.tar.gz -C /tmp", "tar xzf site.tar.gz -C /tmp"],
         "h": "-C changes the target directory.",
         "e": "-C DIR extracts somewhere else."},
        {"q": "Create a bzip2-compressed archive logs.tar.bz2 of /var/log.",
         "a": ["tar -cjf logs.tar.bz2 /var/log", "tar cjf logs.tar.bz2 /var/log",
               "tar -cjvf logs.tar.bz2 /var/log", "tar cjvf logs.tar.bz2 /var/log"],
         "h": "bzip2 is -j (gzip is -z).", "e": "-j = bzip2, -z = gzip, -J = xz."},
        {"q": "Extract the xz-compressed archive data.tar.xz.",
         "a": ["tar -xJf data.tar.xz", "tar xJf data.tar.xz"],
         "h": "xz uses capital J.", "e": "-J handles .xz archives."},
        {"q": "Create an UNcompressed archive home.tar of /home.",
         "a": ["tar -cf home.tar /home", "tar cf home.tar /home",
               "tar -cvf home.tar /home", "tar cvf home.tar /home"],
         "h": "Just create + file, no compression flag.",
         "e": "Without -z/-j/-J tar archives without compressing."},
    ],
    "gzip": [
        {"q": "Decompress huge.log.gz back to huge.log.",
         "a": ["gunzip huge.log.gz", "gzip -d huge.log.gz"],
         "h": "gunzip, or gzip with a flag.", "e": "gunzip = gzip -d."},
        {"q": "Compress report.txt but KEEP the original file too.",
         "a": ["gzip -k report.txt"], "h": "k for keep.",
         "e": "-k keeps the original instead of replacing it."},
        {"q": "View the contents of notes.txt.gz WITHOUT decompressing it.",
         "a": ["zcat notes.txt.gz", "zless notes.txt.gz"],
         "h": "There's a z-flavored cat.", "e": "zcat/zless/zgrep read .gz directly."},
        {"q": "Search for 'error' inside app.log.gz without unpacking it.",
         "a": ["zgrep error app.log.gz", "zgrep 'error' app.log.gz"],
         "h": "z + grep.", "e": "zgrep greps compressed files in place."},
    ],
    "grep": [
        {"q": "Show lines of app.log that do NOT contain 'debug'.",
         "a": ["grep -v debug app.log", "grep -v 'debug' app.log"],
         "h": "Invert the match.", "e": "-v inverts: print non-matching lines."},
        {"q": "COUNT how many lines in auth.log contain 'fail'.",
         "a": ["grep -c fail auth.log", "grep -c 'fail' auth.log"],
         "h": "c for count.", "e": "-c prints a count instead of the lines."},
        {"q": "Find 'root' in /etc/passwd, showing line numbers.",
         "a": ["grep -n root /etc/passwd"], "h": "n for numbers.",
         "e": "-n prefixes each match with its line number."},
        {"q": "Recursively list ONLY the filenames under src that contain 'TODO'.",
         "a": ["grep -rl TODO src", "grep -lr TODO src", "grep -rl 'TODO' src"],
         "h": "-l lists files; combine with -r.",
         "e": "-l suppresses the matching text, printing filenames once."},
        {"q": "Show each match of 'panic' in syslog WITH 2 lines of context around it.",
         "a": ["grep -C 2 panic syslog", "grep -C2 panic syslog"],
         "h": "There are context flags: -A after, -B before, -C both.",
         "e": "-C 2 shows 2 lines before AND after each match."},
    ],
    "find": [
        {"q": "Find every DIRECTORY named 'cache' starting from /.",
         "a": ["find / -type d -name cache", "find / -name cache -type d",
               "find / -type d -name 'cache'"],
         "h": "-type d filters to directories.", "e": "-type d = dirs, f = files."},
        {"q": "Find files under /etc modified in the last 7 days.",
         "a": ["find /etc -mtime -7", "find /etc -type f -mtime -7"],
         "h": "-mtime in days; minus means 'less than'.",
         "e": "-mtime -7 = modified < 7 days ago; +7 = older than 7."},
        {"q": "Find empty files in /tmp.",
         "a": ["find /tmp -type f -empty", "find /tmp -empty -type f",
               "find /tmp -empty"],
         "h": "There's an -empty test.", "e": "-empty matches zero-length files/dirs."},
        {"q": "Find all files owned by the user bob, system-wide.",
         "a": ["find / -user bob"], "h": "-user.",
         "e": "-user filters by owner; -group by group."},
        {"q": "Find the file named 'hosts' anywhere under /etc.",
         "a": ["find /etc -name hosts", "find /etc -type f -name hosts",
               "find /etc -name hosts -type f"],
         "h": "-name matches the filename.",
         "e": "-name does exact-name matching; -iname ignores case."},
    ],
    "chmod": [
        {"q": "Set notes.txt to rw for owner, read-only for group and others (octal).",
         "a": ["chmod 644 notes.txt"], "h": "rw=6, r=4.",
         "e": "644 = rw- r-- r--, the classic file default."},
        {"q": "Remove write permission from group AND others on secret.txt (symbolic).",
         "a": ["chmod go-w secret.txt"], "h": "Combine who letters: go.",
         "e": "go-w strips write from group and other in one shot."},
        {"q": "Recursively set /srv/app to 750.",
         "a": ["chmod -R 750 /srv/app", "chmod 750 -R /srv/app"],
         "h": "-R recurses.", "e": "750 = rwx r-x ---."},
        {"q": "Set /usr/local/bin/tool to 755 WITH the setuid bit (octal).",
         "a": ["chmod 4755 /usr/local/bin/tool"],
         "h": "A 4th leading digit: setuid=4, setgid=2, sticky=1.",
         "e": "4755: the leading 4 is setuid - it runs as the file's owner."},
        {"q": "Put the sticky bit on the shared dir /shared with full 777 perms (octal).",
         "a": ["chmod 1777 /shared"],
         "h": "Sticky = leading 1.",
         "e": "1777 like /tmp: everyone writes, only owners delete their files."},
    ],
    "chown": [
        {"q": "Recursively give /srv/web to user www-data, group www-data.",
         "a": ["chown -R www-data:www-data /srv/web",
               "chown www-data:www-data -R /srv/web"],
         "h": "user:group plus recursion.", "e": "-R applies down the whole tree."},
        {"q": "Change ONLY the group of data.db to 'dba'.",
         "a": ["chgrp dba data.db", "chown :dba data.db"],
         "h": "chgrp, or chown with an empty user part.",
         "e": "chown :group changes group only - same as chgrp."},
        {"q": "Make alice the owner of report.txt (leave the group alone).",
         "a": ["chown alice report.txt"], "h": "Just the user, no colon.",
         "e": "Without :group, only the owner changes."},
    ],
    "kill": [
        {"q": "Politely ask PID 3300 to terminate (default signal).",
         "a": ["kill 3300", "kill -15 3300", "kill -TERM 3300"],
         "h": "No -9 needed - the default is TERM.",
         "e": "Plain kill sends SIGTERM (15), the clean-shutdown signal."},
        {"q": "Send HUP to PID 812 so the daemon reloads its config.",
         "a": ["kill -1 812", "kill -HUP 812", "kill -s HUP 812", "kill -s 1 812"],
         "h": "HUP is signal 1.",
         "e": "Many daemons re-read config on SIGHUP (1)."},
        {"q": "Force-kill every process named 'chrome'.",
         "a": ["killall -9 chrome", "pkill -9 chrome"],
         "h": "By name, with the KILL signal.",
         "e": "killall/pkill accept signals just like kill."},
        {"q": "Kill ALL processes belonging to the user bob.",
         "a": ["pkill -u bob", "pkill -KILL -u bob", "killall -u bob"],
         "h": "pkill can target a user.",
         "e": "-u filters by user - careful, it hits everything they run."},
    ],
    "ss": [
        {"q": "Show listening TCP sockets only, numeric ports.",
         "a": ["ss -tln", "ss -ltn", "ss -nlt", "ss -t -l -n"],
         "h": "Drop the u and p this time.", "e": "-t TCP, -l listening, -n numeric."},
        {"q": "Show a one-screen summary of socket statistics.",
         "a": ["ss -s"], "h": "s for summary.",
         "e": "-s totals sockets by state - a fast load check."},
        {"q": "Show listening UDP sockets, numeric.",
         "a": ["ss -uln", "ss -lun", "ss -nlu", "ss -u -l -n"],
         "h": "u instead of t.", "e": "-u selects UDP."},
    ],
    "ip": [
        {"q": "Bring the interface eth0 UP.",
         "a": ["ip link set eth0 up", "ip link set dev eth0 up"],
         "h": "It's a link operation.", "e": "ip link set <dev> up/down toggles state."},
        {"q": "Add the address 192.168.1.50/24 to eth0.",
         "a": ["ip addr add 192.168.1.50/24 dev eth0",
               "ip a add 192.168.1.50/24 dev eth0",
               "ip address add 192.168.1.50/24 dev eth0"],
         "h": "addr add ... dev ...", "e": "Runtime only - persists via netplan/NM."},
        {"q": "Show all interfaces in BRIEF one-line-each format.",
         "a": ["ip -br a", "ip -br addr", "ip -br address", "ip -brief a",
               "ip -brief addr"],
         "h": "There's a -br output mode.", "e": "-br is great for quick scans."},
        {"q": "Show the ARP/neighbor table.",
         "a": ["ip neigh", "ip n", "ip neighbor", "ip neighbour", "ip neigh show"],
         "h": "Neighbors.", "e": "ip neigh replaced the old arp command."},
        {"q": "Add a default route via gateway 10.0.0.1.",
         "a": ["ip route add default via 10.0.0.1", "ip r add default via 10.0.0.1"],
         "h": "route add default via ...",
         "e": "The default route is where non-local traffic goes."},
    ],
    "podman": [
        {"q": "Stop the running container named 'web'.",
         "a": ["podman stop web", "docker stop web"], "h": "The verb is stop.",
         "e": "stop sends TERM, then KILL after a grace period."},
        {"q": "Delete the stopped container 'web'.",
         "a": ["podman rm web", "docker rm web"], "h": "rm for containers.",
         "e": "rm removes a container; rmi removes an IMAGE."},
        {"q": "List the container images stored locally.",
         "a": ["podman images", "docker images", "podman image ls",
               "docker image ls"],
         "h": "images (plural).", "e": "Shows repo, tag, ID, and size."},
        {"q": "Download the nginx image from a registry without running it.",
         "a": ["podman pull nginx", "docker pull nginx",
               "podman pull nginx:latest", "docker pull nginx:latest"],
         "h": "The verb is pull.", "e": "pull fetches; run would pull AND start."},
        {"q": "Run 'myapp' detached with the environment variable MODE=prod.",
         "a": ["podman run -d -e MODE=prod myapp", "docker run -d -e MODE=prod myapp",
               "podman run -e MODE=prod -d myapp", "docker run -e MODE=prod -d myapp"],
         "h": "-e KEY=VALUE.", "e": "-e injects environment variables."},
        {"q": "Run 'db' detached, mounting host /data into the container at /var/lib/data.",
         "a": ["podman run -d -v /data:/var/lib/data db",
               "docker run -d -v /data:/var/lib/data db",
               "podman run -v /data:/var/lib/data -d db",
               "docker run -v /data:/var/lib/data -d db"],
         "h": "-v host:container.", "e": "-v maps a volume host-path:container-path."},
        {"q": "Show the full JSON details of the container 'web'.",
         "a": ["podman inspect web", "docker inspect web"],
         "h": "The verb is inspect.", "e": "inspect dumps config, network, mounts."},
    ],
    "compose": [
        {"q": "Tear down the whole Compose application (stop + remove).",
         "a": ["docker compose down", "docker-compose down"],
         "h": "The opposite of up.", "e": "down stops and removes services/networks."},
        {"q": "View the logs of all Compose services.",
         "a": ["docker compose logs", "docker-compose logs"],
         "h": "Same word as the container command.", "e": "Add -f to follow live."},
        {"q": "List the running Compose services.",
         "a": ["docker compose ps", "docker-compose ps"],
         "h": "Like container ps, but via compose.",
         "e": "Shows each service's state and ports."},
    ],
    "lvm": [
        {"q": "List all LOGICAL volumes (short summary).",
         "a": ["lvs", "lvdisplay"], "h": "Two letters + s.",
         "e": "lvs is the compact list; lvdisplay the verbose one."},
        {"q": "List all VOLUME GROUPS (short summary).",
         "a": ["vgs", "vgdisplay"], "h": "Same pattern, vg.",
         "e": "vgs shows size, free space, PV/LV counts."},
        {"q": "List all PHYSICAL volumes (short summary).",
         "a": ["pvs", "pvdisplay"], "h": "Same pattern, pv.",
         "e": "pvs shows each disk's VG membership and free space."},
        {"q": "Add the new disk /dev/sdc into the existing volume group 'datavg'.",
         "a": ["vgextend datavg /dev/sdc"], "h": "Extend the VG.",
         "e": "vgextend grows the pool; pvcreate the disk first."},
        {"q": "Delete the logical volume 'old' from volume group 'datavg'.",
         "a": ["lvremove /dev/datavg/old", "lvremove datavg/old"],
         "h": "lvremove takes the LV path.", "e": "Destroys the LV and its data."},
        {"q": "Create LV 'big' in 'datavg' using ALL remaining free space.",
         "a": ["lvcreate -l 100%FREE -n big datavg",
               "lvcreate -n big -l 100%FREE datavg"],
         "h": "Lowercase -l with a percentage.",
         "e": "-l 100%FREE allocates by extents; -L takes fixed sizes."},
    ],
    "mount": [
        {"q": "Remount the already-mounted /data as read-write.",
         "a": ["mount -o remount,rw /data"], "h": "remount,rw in one -o.",
         "e": "remount changes options without unmounting."},
        {"q": "Unmount the filesystem at /mnt/usb.",
         "a": ["umount /mnt/usb"], "h": "Note: umount, not unmount.",
         "e": "umount detaches; fails if files are in use (check with lsof)."},
        {"q": "Mount the NFS export server:/share at /mnt/nfs.",
         "a": ["mount -t nfs server:/share /mnt/nfs"],
         "h": "-t names the filesystem type.",
         "e": "-t nfs + host:/path mounts a network share."},
    ],
    "firewall-cmd": [
        {"q": "Show the full configuration of the current firewalld zone.",
         "a": ["firewall-cmd --list-all"], "h": "--list-all.",
         "e": "Shows services, ports, and rich rules in the active zone."},
        {"q": "Permanently allow the https SERVICE (not the raw port).",
         "a": ["firewall-cmd --permanent --add-service=https",
               "firewall-cmd --add-service=https --permanent"],
         "h": "--add-service instead of --add-port.",
         "e": "Services are named bundles of ports; then --reload."},
        {"q": "Permanently REMOVE the opening for port 8080/tcp.",
         "a": ["firewall-cmd --permanent --remove-port=8080/tcp",
               "firewall-cmd --remove-port=8080/tcp --permanent"],
         "h": "remove instead of add.", "e": "Follow with --reload to apply."},
        {"q": "Show which zones are active and on which interfaces.",
         "a": ["firewall-cmd --get-active-zones"], "h": "get-active-zones.",
         "e": "Maps interfaces to zones - key when traffic isn't matching rules."},
    ],
    "ufw": [
        {"q": "Turn the ufw firewall ON.",
         "a": ["ufw enable"], "h": "One word.", "e": "enable activates and persists."},
        {"q": "Block inbound telnet (port 23).",
         "a": ["ufw deny 23", "ufw deny 23/tcp", "ufw deny telnet"],
         "h": "The opposite of allow.", "e": "deny drops matching traffic."},
        {"q": "Show the rules WITH index numbers (for deleting by number).",
         "a": ["ufw status numbered"], "h": "status, plus a word.",
         "e": "Numbered output enables `ufw delete <n>`."},
        {"q": "Allow ALL traffic from the single host 10.0.0.5.",
         "a": ["ufw allow from 10.0.0.5"], "h": "allow from <ip>.",
         "e": "Source-based rule - no port means all ports."},
    ],
    "useradd": [
        {"q": "Change bob's login shell to /usr/sbin/nologin (block shell access).",
         "a": ["usermod -s /usr/sbin/nologin bob"],
         "h": "usermod with the shell flag.",
         "e": "nologin politely refuses interactive logins."},
        {"q": "Create a SYSTEM account 'svc' without a home directory.",
         "a": ["useradd -r -M svc", "useradd -M -r svc"],
         "h": "-r for system account, -M for no home.",
         "e": "-r uses the system UID range; -M skips home creation."},
        {"q": "Delete the user carol AND remove her home directory.",
         "a": ["userdel -r carol"], "h": "userdel plus one flag.",
         "e": "-r also removes the home dir and mail spool."},
        {"q": "Unlock bob's previously locked account.",
         "a": ["usermod -U bob", "passwd -u bob"],
         "h": "The capital/lowercase opposites of -L/-l.",
         "e": "usermod -U / passwd -u remove the lock."},
        {"q": "Make the account 'temp' expire on 2026-12-31.",
         "a": ["usermod -e 2026-12-31 temp", "chage -E 2026-12-31 temp"],
         "h": "usermod -e or chage -E.",
         "e": "Expiry disables the whole account on that date."},
    ],
    "apt": [
        {"q": "Refresh the package index (do this before installing).",
         "a": ["apt update", "apt-get update"], "h": "update vs upgrade.",
         "e": "update refreshes lists; upgrade installs newer versions."},
        {"q": "Remove the package htop.",
         "a": ["apt remove htop", "apt-get remove htop"],
         "h": "The opposite of install.",
         "e": "remove keeps config files; purge deletes them too."},
        {"q": "Upgrade all installed packages.",
         "a": ["apt upgrade", "apt-get upgrade"], "h": "After an update.",
         "e": "upgrade applies everything the refreshed index offers."},
    ],
    "dnf": [
        {"q": "Search the repositories for packages matching 'nginx'.",
         "a": ["dnf search nginx", "yum search nginx"], "h": "The verb is search.",
         "e": "search matches names/summaries."},
        {"q": "Remove the package httpd.",
         "a": ["dnf remove httpd", "yum remove httpd"], "h": "Same verb as apt.",
         "e": "Also removes dependent packages - read the prompt!"},
        {"q": "List which installed packages have updates available.",
         "a": ["dnf check-update", "yum check-update"], "h": "check-...",
         "e": "check-update lists without installing."},
    ],
    "ssh-keygen": [
        {"q": "Generate a modern ed25519 SSH key pair.",
         "a": ["ssh-keygen -t ed25519"], "h": "-t picks the key type.",
         "e": "ed25519 is the current recommended type."},
        {"q": "Install your public key on web01 for the user alice.",
         "a": ["ssh-copy-id alice@web01"], "h": "There's a dedicated copy tool.",
         "e": "ssh-copy-id appends to ~/.ssh/authorized_keys remotely."},
        {"q": "SSH to host 'bastion' as admin on the non-standard port 2222.",
         "a": ["ssh -p 2222 admin@bastion", "ssh admin@bastion -p 2222"],
         "h": "-p for port (capital -P is scp!).",
         "e": "ssh uses -p; scp confusingly uses -P."},
    ],
    "setfacl": [
        {"q": "Remove bob's ACL entry from project.txt.",
         "a": ["setfacl -x u:bob project.txt"], "h": "-x removes an entry.",
         "e": "-x deletes one entry; -b strips ALL ACLs."},
        {"q": "View the ACLs currently set on project.txt.",
         "a": ["getfacl project.txt"], "h": "The reading twin of setfacl.",
         "e": "getfacl prints owner, group, and every ACL entry."},
        {"q": "Strip ALL ACL entries from project.txt in one go.",
         "a": ["setfacl -b project.txt"],
         "h": "One flag removes everything.",
         "e": "-b (blank) removes every ACL entry, leaving the base permissions."},
    ],
    "chattr": [
        {"q": "Remove the immutable attribute from /etc/resolv.conf.",
         "a": ["chattr -i /etc/resolv.conf"], "h": "Minus instead of plus.",
         "e": "-i clears immutable so the file can change again."},
        {"q": "List the attributes set on /etc/resolv.conf.",
         "a": ["lsattr /etc/resolv.conf"], "h": "The ls of attributes.",
         "e": "lsattr shows flags like i (immutable) and a (append-only)."},
    ],
    "selinux": [
        {"q": "Check which SELinux mode the system is in right now.",
         "a": ["getenforce", "sestatus"], "h": "get-...",
         "e": "getenforce prints Enforcing/Permissive/Disabled."},
        {"q": "List ALL SELinux booleans and their current values.",
         "a": ["getsebool -a"], "h": "getsebool with one flag.",
         "e": "-a dumps every boolean - grep it for the one you need."},
        {"q": "List files in the current directory WITH their SELinux contexts.",
         "a": ["ls -Z"], "h": "A special ls flag.",
         "e": "-Z shows user:role:type:level labels."},
        {"q": "Manually set index.html's context TYPE to httpd_sys_content_t.",
         "a": ["chcon -t httpd_sys_content_t index.html"],
         "h": "chcon with -t.",
         "e": "chcon changes contexts directly (restorecon resets to policy)."},
    ],
    "dig": [
        {"q": "Resolve example.com showing ONLY the bare answer (no sections).",
         "a": ["dig +short example.com", "dig example.com +short"],
         "h": "A +option trims output.", "e": "+short prints just the records."},
        {"q": "Query the MX (mail) records for example.com.",
         "a": ["dig example.com MX", "dig MX example.com", "dig example.com mx",
               "dig mx example.com"],
         "h": "Record type after the name.", "e": "Add a type: MX, NS, TXT, AAAA..."},
        {"q": "Resolve example.com using Google's resolver 8.8.8.8 specifically.",
         "a": ["dig @8.8.8.8 example.com", "dig example.com @8.8.8.8"],
         "h": "@server picks the resolver.",
         "e": "@8.8.8.8 bypasses /etc/resolv.conf - great for isolating DNS issues."},
    ],
    "tcpdump": [
        {"q": "Capture on eth0, but only traffic on port 443.",
         "a": ["tcpdump -i eth0 port 443", "tcpdump port 443 -i eth0"],
         "h": "Append a capture filter.", "e": "Filters like 'port N' cut the noise."},
        {"q": "Capture on eth0 and SAVE packets to cap.pcap for Wireshark.",
         "a": ["tcpdump -i eth0 -w cap.pcap", "tcpdump -w cap.pcap -i eth0"],
         "h": "-w writes a file.", "e": "-w saves raw packets; -r reads them back."},
        {"q": "Capture on eth0, only traffic to/from host 10.0.0.5.",
         "a": ["tcpdump -i eth0 host 10.0.0.5", "tcpdump host 10.0.0.5 -i eth0"],
         "h": "host <ip> filter.", "e": "'host' matches either direction."},
    ],
    "modprobe": [
        {"q": "List all currently loaded kernel modules.",
         "a": ["lsmod"], "h": "The ls of modules.",
         "e": "lsmod reads /proc/modules."},
        {"q": "Rebuild the module dependency map after installing new modules.",
         "a": ["depmod", "depmod -a"], "h": "dep-...",
         "e": "depmod regenerates modules.dep, which modprobe relies on."},
        {"q": "Show only the PARAMETERS the e1000e module accepts.",
         "a": ["modinfo -p e1000e"], "h": "modinfo with one flag.",
         "e": "-p limits modinfo to parameters."},
    ],
    "dracut": [
        {"q": "Force-rebuild the initramfs for the SPECIFIC kernel 6.8.0.",
         "a": ["dracut -f --kver 6.8.0", "dracut --kver 6.8.0 -f"],
         "h": "--kver picks the kernel.",
         "e": "Without --kver, dracut builds for the running kernel."},
        {"q": "On Debian/Ubuntu, regenerate the initramfs for the current kernel.",
         "a": ["update-initramfs -u"], "h": "Debian's own tool.",
         "e": "update-initramfs -u is Debian's dracut -f equivalent."},
    ],
    "rsync": [
        {"q": "DRY-RUN the sync of /home/data/ to backup01:/srv/data (show, don't copy).",
         "a": ["rsync -avzn /home/data/ backup01:/srv/data",
               "rsync -avz -n /home/data/ backup01:/srv/data",
               "rsync -avz --dry-run /home/data/ backup01:/srv/data",
               "rsync -n -avz /home/data/ backup01:/srv/data"],
         "h": "Add the dry-run flag.", "e": "-n / --dry-run previews changes."},
        {"q": "Mirror /home/data/ to backup01:/srv/data, DELETING remote files that no longer exist locally.",
         "a": ["rsync -avz --delete /home/data/ backup01:/srv/data",
               "rsync --delete -avz /home/data/ backup01:/srv/data"],
         "h": "--delete makes it a true mirror.",
         "e": "--delete removes extraneous files on the destination."},
        {"q": "Locally copy /src/ into /dst preserving permissions and times.",
         "a": ["rsync -av /src/ /dst", "rsync -av /src/ /dst/"],
         "h": "rsync works locally too.", "e": "-a alone covers perms/times/links."},
    ],
    "crontab": [
        {"q": "List your current crontab without editing it.",
         "a": ["crontab -l"], "h": "l for list.", "e": "-l prints, -e edits."},
        {"q": "Delete your entire crontab.",
         "a": ["crontab -r"], "h": "r for remove (careful - no confirmation!).",
         "e": "-r wipes the whole crontab silently."},
        {"q": "Edit the crontab of the user 'deploy' (as root).",
         "a": ["crontab -e -u deploy", "crontab -u deploy -e"],
         "h": "-u targets another user.",
         "e": "-u USER works with -l, -e, and -r."},
    ],
    "git": [
        {"q": "Stage ALL changed files in the repo.",
         "a": ["git add .", "git add -A", "git add --all"],
         "h": "add with a catch-all.", "e": "'.' stages the tree; -A includes deletions."},
        {"q": "Show which files are modified/staged/untracked.",
         "a": ["git status"], "h": "One word.",
         "e": "status is the safe first command in any repo."},
        {"q": "Show the commit history, one line per commit.",
         "a": ["git log --oneline"], "h": "log plus a format flag.",
         "e": "--oneline compresses each commit to hash + subject."},
        {"q": "Upload your local commits to the remote.",
         "a": ["git push"], "h": "One word.",
         "e": "push sends commits; pull fetches + merges."},
    ],
    "kubectl": [
        {"q": "List the pods in the current namespace.",
         "a": ["kubectl get pods", "kubectl get po"], "h": "get + resource.",
         "e": "get is the universal lister: pods, svc, deploy..."},
        {"q": "View the logs of the pod 'mypod'.",
         "a": ["kubectl logs mypod"], "h": "Same word containers use.",
         "e": "Add -f to follow; -c CONTAINER for multi-container pods."},
        {"q": "Show detailed status and events for the deployment 'web'.",
         "a": ["kubectl describe deployment web", "kubectl describe deploy web"],
         "h": "More detail than get.",
         "e": "describe includes the event log - first stop when pods won't start."},
        {"q": "Delete everything defined in deploy.yaml.",
         "a": ["kubectl delete -f deploy.yaml"], "h": "The inverse of apply -f.",
         "e": "delete -f removes the manifest's resources."},
    ],
    "ansible": [
        {"q": "DRY-RUN the playbook site.yml (report changes, don't make them).",
         "a": ["ansible-playbook site.yml --check",
               "ansible-playbook --check site.yml"],
         "h": "--check.", "e": "--check is Ansible's dry-run mode."},
        {"q": "Run the shell command 'uptime' on all hosts via the command module.",
         "a": ["ansible all -m command -a uptime", "ansible all -m command -a 'uptime'",
               'ansible all -m command -a "uptime"'],
         "h": "-m command -a '<cmd>'.",
         "e": "-a passes arguments to the module."},
        {"q": "List which hosts an 'all' pattern would target (no execution).",
         "a": ["ansible all --list-hosts"], "h": "--list-hosts.",
         "e": "Quick inventory sanity check before a real run."},
    ],
    "systemd-analyze": [
        {"q": "Show the TOTAL time the last boot took (kernel + userspace).",
         "a": ["systemd-analyze", "systemd-analyze time"],
         "h": "The bare command already answers this.",
         "e": "Plain systemd-analyze prints the boot time summary."},
        {"q": "Show the chain of units that actually DELAYED boot.",
         "a": ["systemd-analyze critical-chain"], "h": "critical-...",
         "e": "critical-chain shows the dependency path, not just slow units."},
    ],
    "mkfs": [
        {"q": "Format /dev/sdd1 with XFS.",
         "a": ["mkfs.xfs /dev/sdd1", "mkfs -t xfs /dev/sdd1"],
         "h": "Same pattern as ext4.", "e": "mkfs.xfs or mkfs -t xfs."},
        {"q": "Format /dev/sdc1 as ext4 WITH the label 'data'.",
         "a": ["mkfs.ext4 -L data /dev/sdc1", "mkfs.ext4 /dev/sdc1 -L data"],
         "h": "-L sets a label.", "e": "Labels let fstab mount by LABEL=data."},
    ],
    "fsresize": [
        {"q": "Grow the XFS filesystem mounted at /srv.",
         "a": ["xfs_growfs /srv"], "h": "Mount point, not device.",
         "e": "xfs_growfs always takes the mount point."},
        {"q": "Shrink the ext4 on /dev/datavg/web down to exactly 10G (it's unmounted).",
         "a": ["resize2fs /dev/datavg/web 10G"],
         "h": "resize2fs takes an optional target size.",
         "e": "With a size argument resize2fs shrinks; only ext supports shrinking."},
    ],
    "virsh": [
        {"q": "Power on the VM named 'webvm'.",
         "a": ["virsh start webvm"], "h": "The verb is start.",
         "e": "start boots a defined domain."},
        {"q": "Gracefully shut down the VM 'webvm'.",
         "a": ["virsh shutdown webvm"], "h": "Graceful, not destroy.",
         "e": "shutdown asks the guest OS; destroy pulls the plug."},
    ],
    "dmesg": [
        {"q": "Show kernel messages with human-readable timestamps.",
         "a": ["dmesg -T", "dmesg --ctime"], "h": "Capital T.",
         "e": "-T converts seconds-since-boot to wall-clock time."},
        {"q": "FOLLOW the kernel ring buffer live as new messages arrive.",
         "a": ["dmesg -w", "dmesg --follow"], "h": "w for wait/watch.",
         "e": "-w streams new kernel messages like tail -f."},
        {"q": "Show only error-level kernel messages and worse.",
         "a": ["dmesg -l err", "dmesg --level=err", "dmesg -l err,crit"],
         "h": "-l takes a level name.", "e": "-l filters by log level."},
    ],
    "lsblk": [
        {"q": "Show block devices WITH their filesystems, labels, and UUIDs.",
         "a": ["lsblk -f", "lsblk --fs"], "h": "f for filesystem info.",
         "e": "-f adds FSTYPE, LABEL, and UUID columns - handy for fstab."},
        {"q": "Show block devices with FULL device paths (/dev/...).",
         "a": ["lsblk -p", "lsblk --paths"], "h": "p for paths.",
         "e": "-p prints /dev/sda1 instead of just sda1."},
    ],
    "df": [
        {"q": "Show disk usage including each filesystem's TYPE.",
         "a": ["df -hT", "df -Th", "df -T"], "h": "Capital T adds a column.",
         "e": "-T shows ext4/xfs/tmpfs per mount."},
        {"q": "Show INODE usage instead of block usage.",
         "a": ["df -i", "df -hi", "df -ih"], "h": "i for inodes.",
         "e": "A full inode table blocks new files even with free space."},
        {"q": "Show usage for ONLY the filesystem containing /var.",
         "a": ["df -h /var", "df /var"], "h": "Just pass the path.",
         "e": "df with a path reports only that path's filesystem."},
    ],
    "du": [
        {"q": "Show the size of each immediate subdirectory of /var (one level deep), human-readable.",
         "a": ["du -h --max-depth=1 /var", "du --max-depth=1 -h /var",
               "du -h -d 1 /var", "du -d 1 -h /var"],
         "h": "There's a depth limiter.",
         "e": "--max-depth=1 (or -d 1) stops the recursion one level down."},
        {"q": "Show sizes of EVERY file and directory under /opt, human-readable.",
         "a": ["du -ah /opt", "du -ha /opt", "du -a -h /opt"],
         "h": "a for all (files too).",
         "e": "-a includes individual files, not just directory totals."},
    ],
    "free": [
        {"q": "Show memory in whole MEBIBYTES.",
         "a": ["free -m"], "h": "One letter.", "e": "-m for MiB, -g for GiB."},
        {"q": "Show memory refreshing every 5 seconds continuously.",
         "a": ["free -s 5", "free -h -s 5", "free -s 5 -h"],
         "h": "s for seconds.", "e": "-s N repeats the report every N seconds."},
        {"q": "Show memory with a TOTAL line summing RAM + swap.",
         "a": ["free -t", "free -ht", "free -th"], "h": "t for total.",
         "e": "-t appends a combined total row."},
    ],
    "ps": [
        {"q": "Show only the processes belonging to the user alice.",
         "a": ["ps -u alice", "ps -fu alice", "ps -u alice -f"],
         "h": "-u takes a username.", "e": "-u filters the table by user."},
        {"q": "Show all processes as a TREE of parents and children.",
         "a": ["pstree", "ps -ef --forest", "ps aux --forest", "ps --forest"],
         "h": "pstree, or a ps --long-flag.",
         "e": "--forest draws ASCII parent/child lines; pstree is dedicated."},
        {"q": "Show every process in System V style (full format).",
         "a": ["ps -ef"], "h": "The dash style this time.",
         "e": "-e every process, -f full format - the SysV twin of aux."},
    ],
    "fsck": [
        {"q": "Check /dev/sdc1 WITHOUT making any changes (report only).",
         "a": ["fsck -n /dev/sdc1", "fsck -N /dev/sdc1"],
         "h": "Answer 'no' to everything.",
         "e": "-n answers no to all repair prompts - a safe dry inspection."},
        {"q": "Force a check of /dev/sdc1 even though it's marked clean.",
         "a": ["fsck -f /dev/sdc1", "fsck -fy /dev/sdc1"],
         "h": "f for force.", "e": "-f checks even when the FS claims it's clean."},
    ],
    "mtr": [
        {"q": "Run mtr to 8.8.8.8 in one-shot REPORT mode (no live screen).",
         "a": ["mtr -r 8.8.8.8", "mtr --report 8.8.8.8", "mtr -rw 8.8.8.8"],
         "h": "r for report.", "e": "-r runs a batch and prints a summary - script-friendly."},
        {"q": "Run mtr to 8.8.8.8 with exactly 20 probe cycles.",
         "a": ["mtr -c 20 8.8.8.8", "mtr -r -c 20 8.8.8.8", "mtr -c 20 -r 8.8.8.8"],
         "h": "c for count.", "e": "-c N sends N pings per hop then stops."},
        {"q": "Run mtr to 8.8.8.8 using numeric IPs only (skip DNS lookups).",
         "a": ["mtr -n 8.8.8.8", "mtr -rn 8.8.8.8", "mtr -nr 8.8.8.8"],
         "h": "Same letter ss uses for numeric.",
         "e": "-n avoids slow reverse-DNS on every hop."},
    ],
    "lsof": [
        {"q": "List all files opened by PID 1234.",
         "a": ["lsof -p 1234"], "h": "p for PID.",
         "e": "-p shows everything one process has open."},
        {"q": "List all files opened by the user bob.",
         "a": ["lsof -u bob"], "h": "u for user.",
         "e": "-u filters by owner - useful before unmounting their disk."},
        {"q": "List ALL network connections (any port).",
         "a": ["lsof -i"], "h": "Same flag as the port version, no port.",
         "e": "-i alone lists every internet socket."},
    ],
    "renice": [
        {"q": "As root, RAISE the priority of PID 2000 by setting nice to -5.",
         "a": ["renice -5 2000", "renice -n -5 2000", "renice -n -5 -p 2000",
               "renice -5 -p 2000"],
         "h": "Negative nice = higher priority (root only).",
         "e": "Nice runs -20 (highest priority) to 19 (lowest)."},
        {"q": "LAUNCH ./batch.sh at low priority (nice value 10).",
         "a": ["nice -n 10 ./batch.sh", "nice -10 ./batch.sh"],
         "h": "nice at launch, renice afterwards.",
         "e": "nice -n 10 starts the process already niced."},
    ],
    "nohup": [
        {"q": "List the background jobs of your current shell.",
         "a": ["jobs"], "h": "One word.",
         "e": "jobs shows your shell's job table with %numbers."},
        {"q": "Resume the stopped job number 2 in the BACKGROUND.",
         "a": ["bg %2", "bg 2"], "h": "bg + job number.",
         "e": "Ctrl+Z stops a job; bg resumes it in the background."},
        {"q": "Bring job number 1 to the FOREGROUND.",
         "a": ["fg %1", "fg 1"], "h": "The opposite of bg.",
         "e": "fg reattaches a job to your terminal."},
    ],
    "vmstat": [
        {"q": "Print a one-shot summary of memory statistics (no interval).",
         "a": ["vmstat -s"], "h": "s for summary.",
         "e": "-s prints totals once instead of sampling."},
        {"q": "Sample stats every 2 seconds, but only 5 times, then stop.",
         "a": ["vmstat 2 5"], "h": "Interval then count.",
         "e": "vmstat INTERVAL COUNT bounds the run - good for scripts."},
    ],
    "iostat": [
        {"q": "Show ONLY device I/O (skip the CPU section), refreshing every 5s.",
         "a": ["iostat -d 5"], "h": "d for devices.",
         "e": "-d limits output to the device report."},
        {"q": "Show extended device stats but HIDE idle devices.",
         "a": ["iostat -xz", "iostat -zx", "iostat -x -z"],
         "h": "Add z to your usual -x.", "e": "-z suppresses all-zero devices."},
    ],
    "uptime": [
        {"q": "Show the uptime in friendly words ('up 2 weeks, 3 days...').",
         "a": ["uptime -p", "uptime --pretty"], "h": "p for pretty.",
         "e": "-p prints just a human-friendly duration."},
        {"q": "Show the exact date and time the system BOOTED.",
         "a": ["uptime -s", "uptime --since"], "h": "s for since.",
         "e": "-s prints the boot timestamp."},
    ],
    "sort": [
        {"q": "Sort numbers.txt NUMERICALLY (so 9 comes before 10).",
         "a": ["sort -n numbers.txt"], "h": "n for numeric.",
         "e": "Without -n, sort is alphabetical: 10 < 9."},
        {"q": "Sort names.txt in REVERSE order.",
         "a": ["sort -r names.txt"], "h": "r for reverse.",
         "e": "-r flips the order; combine as -rn for numeric descending."},
        {"q": "Sort list.txt and drop duplicate lines in one step.",
         "a": ["sort -u list.txt"], "h": "One flag replaces piping to uniq.",
         "e": "-u outputs each unique line once (sort + uniq combined)."},
    ],
    "visudo": [
        {"q": "Syntax-CHECK the sudoers file without opening an editor.",
         "a": ["visudo -c"], "h": "c for check.",
         "e": "-c validates /etc/sudoers and everything in sudoers.d."},
        {"q": "Safely edit the drop-in file /etc/sudoers.d/devs.",
         "a": ["visudo -f /etc/sudoers.d/devs"], "h": "-f picks the file.",
         "e": "-f applies visudo's locking and checking to any sudoers file."},
    ],
    "tail": [
        {"q": "Show the last 50 lines of syslog.",
         "a": ["tail -n 50 syslog", "tail -50 syslog", "tail -n50 syslog"],
         "h": "-n sets the line count.", "e": "-n N shows the last N lines."},
    ],
    "cut": [
        {"q": "Print fields 1 AND 3 of the comma-separated users.csv.",
         "a": ["cut -d, -f1,3 users.csv", "cut -f1,3 -d, users.csv"],
         "h": "Comma delimiter, comma-separated field list.",
         "e": "-f takes lists (1,3) and ranges (1-3)."},
        {"q": "Print only the first 8 characters of every line of ids.txt.",
         "a": ["cut -c1-8 ids.txt", "cut -c 1-8 ids.txt"],
         "h": "Cut by characters, not fields.",
         "e": "-c selects character positions; no delimiter needed."},
    ],
    "sed": [
        {"q": "Replace http with https IN PLACE in site.conf (edit the file).",
         "a": ["sed -i 's/http/https/g' site.conf",
               'sed -i "s/http/https/g" site.conf',
               "sed -i s/http/https/g site.conf"],
         "h": "One flag makes the edit stick.",
         "e": "-i writes the change back to the file (use -i.bak to keep a backup)."},
        {"q": "Print ONLY line 5 of config.txt.",
         "a": ["sed -n '5p' config.txt", 'sed -n "5p" config.txt',
               "sed -n 5p config.txt"],
         "h": "-n suppresses auto-print; 5p prints line 5.",
         "e": "sed -n 'Np' is the classic print-one-line idiom."},
    ],
    "curl": [
        {"q": "Download https://example.com and save it to page.html.",
         "a": ["curl -o page.html https://example.com",
               "curl https://example.com -o page.html"],
         "h": "-o names the output file.",
         "e": "-o saves the body; -O keeps the remote filename."},
    ],
    "dd": [
        {"q": "Restore the image disk.img back ONTO the disk /dev/sdb (4M blocks).",
         "a": ["dd if=disk.img of=/dev/sdb bs=4M",
               "dd if=disk.img of=/dev/sdb bs=4M status=progress"],
         "h": "Same dd - just swap which side is if= and of=.",
         "e": "if= reads the image, of= writes the device. Reversed = disaster."},
    ],
    "iptables": [
        {"q": "Append an INPUT rule accepting TCP traffic to port 8080.",
         "a": ["iptables -A INPUT -p tcp --dport 8080 -j ACCEPT"],
         "h": "-A chain, -p proto, --dport port, -j target.",
         "e": "-A appends; -j ACCEPT is the verdict. -D with the same spec deletes it."},
    ],
    "sudo": [
        {"q": "Run the command whoami as the user postgres (via sudo).",
         "a": ["sudo -u postgres whoami"],
         "h": "-u picks the target user.",
         "e": "sudo -u USER runs one command as that user instead of root."},
    ],
    "lastb": [
        {"q": "Show the last 10 SUCCESSFUL logins.",
         "a": ["last -n 10", "last -10"], "h": "last (no b) + a count.",
         "e": "last reads /var/log/wtmp; -n limits the rows."},
        {"q": "Show the system's REBOOT history.",
         "a": ["last reboot"], "h": "last with a pseudo-user.",
         "e": "'reboot' is logged as a pseudo-user in wtmp."},
    ],
}


# --------------------------------------------------------------------------- #
#  Official XK0-006 V8 objective mapping (verified against the CompTIA PDF)
# --------------------------------------------------------------------------- #

OBJ_BY_TOPIC = {
    "Processes": "2.3", "Jobs": "2.3", "Scheduling": "2.3",
    "Kernel modules": "1.2", "Devices": "1.2", "initrd": "1.2",
    "LVM": "1.3", "Filesystems": "1.3", "Mounting": "1.3",
    "Text tools": "1.5", "Redirection": "1.5",
    "Backup": "1.6", "Compression": "1.6", "Virtualization": "1.7",
    "systemd": "2.5", "Boot": "2.5", "Software": "2.4", "Users": "2.2",
    "Containers": "2.6", "Logging": "3.3", "Logs": "3.3",
    "Permissions": "3.1", "ACLs": "3.1", "Attributes": "3.1",
    "SELinux": "3.1", "SSH": "3.1", "Hardening": "3.1",
    "Privilege escalation": "3.1", "firewalld": "3.2", "ufw": "3.2",
    "Scripting": "4.2", "Ansible": "4.1", "Kubernetes": "4.1",
    "Compose": "4.1", "Version control": "4.4",
    "Memory": "5.5", "Performance": "5.5", "Disk I/O": "5.5",
    "Network": "1.4", "DNS": "1.4", "Security": "5.4",
    "Files": "2.1", "Partitions": "1.3", "System settings": "2.5",
    "Firewalls": "3.2",
}
OBJ_OVERRIDES = {"shell-find-size": "2.1"}   # find lives under files/dirs

for _s in SCENARIOS:
    _s["obj"] = OBJ_OVERRIDES.get(_s["id"], OBJ_BY_TOPIC.get(_s["topic"], "?"))


# --------------------------------------------------------------------------- #
#  Parameterized scenarios: names/ports/users/sizes randomize on every ask,
#  so you learn the COMMAND SHAPE, not a memorized string.
# --------------------------------------------------------------------------- #

PARAM_POOLS = {
    "user": ["alice", "bob", "carol", "marco", "dana", "priya"],
    "group": ["docker", "wheel", "devs", "staff", "dba"],
    "file": ["report.txt", "notes.log", "data.csv", "huge.log"],
    "pid": ["4821", "2317", "1054", "3982", "6650"],
    "hport": ["8080", "8081", "8088", "9090"],
    "cname": ["web", "api", "db", "cache"],
    "size": ["10G", "20G", "40G"],
    "lv": ["web", "data", "apps"],
    "port": ["443", "8443", "3306", "9000"],
    "mod": ["vfio", "btrfs", "dummy", "nbd"],
}

PARAM_TEMPLATES = {
    "user-useradd": {
        "prompt": "Create the user '{user}' with a home directory and bash as "
                  "the login shell.",
        "accept": ["useradd -m -s /bin/bash {user}",
                   "useradd -s /bin/bash -m {user}"],
        "hints": ["-m creates the home directory; -s sets the login shell.",
                  "useradd -m -s /bin/bash <name>",
                  "useradd -m -s /bin/bash {user}"],
        "explain": "`useradd -m -s /bin/bash {user}` makes the account, its "
                   "home dir (-m), and sets the shell (-s). Then set a "
                   "password with `passwd`."},
    "user-usermod-group": {
        "prompt": "Add the existing user '{user}' to the '{group}' group "
                  "WITHOUT removing them from any of their current groups.",
        "accept": ["usermod -aG {group} {user}", "usermod -a -G {group} {user}",
                   "usermod -G {group} -a {user}"],
        "hints": ["Just -G would REPLACE the group list - dangerous.",
                  "The -a (append) flag is the key, alongside -G.",
                  "usermod -aG {group} {user}"]},
    "user-lock": {
        "prompt": "Lock the account '{user}' so they can no longer log in "
                  "with their password.",
        "accept": ["usermod -L {user}", "passwd -l {user}",
                   "usermod --lock {user}"],
        "hints": ["Two tools can lock a password.",
                  "usermod -L <user>  or  passwd -l <user>",
                  "usermod -L {user}"]},
    "sec-chown": {
        "prompt": "Change the owner of {file} to '{user}' and the group to "
                  "'{group}' in one command.",
        "accept": ["chown {user}:{group} {file}", "chown {user}.{group} {file}"],
        "hints": ["chown can set user and group together with a colon.",
                  "chown user:group <file>",
                  "chown {user}:{group} {file}"],
        "explain": "`chown {user}:{group} {file}` sets both owner and group. "
                   "Use -R to recurse through a directory tree."},
    "proc-kill9": {
        "prompt": "A hung process with PID {pid} won't respond to a normal "
                  "stop. Forcibly terminate it with the KILL signal.",
        "accept": ["kill -9 {pid}", "kill -KILL {pid}", "kill -s 9 {pid}",
                   "kill -s KILL {pid}"]},
    "proc-renice": {
        "prompt": "Lower the scheduling priority of the already-running PID "
                  "{pid} by setting its nice value to 10.",
        "accept": ["renice 10 {pid}", "renice -n 10 {pid}",
                   "renice 10 -p {pid}", "renice -n 10 -p {pid}"],
        "hints": ["`nice` sets priority at launch; this process is already running.",
                  "The tool for a running process is `renice`.",
                  "renice 10 {pid}"]},
    "ctr-run": {
        "prompt": "Run an nginx container in the background, mapping host "
                  "port {hport} to container port 80.",
        "accept": ["podman run -d -p {hport}:80 nginx",
                   "docker run -d -p {hport}:80 nginx",
                   "podman run -p {hport}:80 -d nginx",
                   "docker run -p {hport}:80 -d nginx"],
        "hints": ["-d detaches (background); -p maps ports host:container.",
                  "<runtime> run -d -p {hport}:80 <image>",
                  "podman run -d -p {hport}:80 nginx"]},
    "ctr-exec": {
        "prompt": "Open an interactive bash shell inside the running "
                  "container named '{cname}'.",
        "accept": ["podman exec -it {cname} bash", "docker exec -it {cname} bash",
                   "podman exec -i -t {cname} bash",
                   "docker exec -i -t {cname} bash"],
        "hints": ["`exec` runs a command in an existing container.",
                  "-i keeps stdin open, -t allocates a TTY: -it.",
                  "podman exec -it {cname} bash"]},
    "lvm-lvcreate": {
        "prompt": "Carve a {size} logical volume named '{lv}' out of the "
                  "volume group 'datavg'.",
        "accept": ["lvcreate -L {size} -n {lv} datavg",
                   "lvcreate -n {lv} -L {size} datavg"],
        "hints": ["Use -L for a fixed size and -n for the name.",
                  "Order: lvcreate -L <size> -n <name> <vg>",
                  "lvcreate -L {size} -n {lv} datavg"]},
    "sec-firewalld-port": {
        "prompt": "Permanently open TCP port {port} in firewalld (the change "
                  "should persist across reloads).",
        "accept": ["firewall-cmd --permanent --add-port={port}/tcp",
                   "firewall-cmd --add-port={port}/tcp --permanent"],
        "hints": ["firewalld's CLI is firewall-cmd.",
                  "--permanent persists; --add-port=PORT/PROTO opens it.",
                  "firewall-cmd --permanent --add-port={port}/tcp"]},
    "dev-modprobe": {
        "prompt": "Load the kernel module named '{mod}' into the running "
                  "kernel (resolving its dependencies automatically).",
        "accept": ["modprobe {mod}"],
        "hints": ["`insmod` loads a single .ko but ignores dependencies.",
                  "The dependency-aware loader is `modprobe`.",
                  "modprobe {mod}"]},
    "backup-gzip": {
        "prompt": "Compress the file {file} in place using gzip.",
        "accept": ["gzip {file}"],
        "hints": ["The classic single-file compressor.",
                  "gzip <file>  (replaces it with file.gz).",
                  "gzip {file}"]},
}


# --------------------------------------------------------------------------- #
#  TRAPS: deliberate near-miss answers with diagnostic feedback.
#  When a wrong answer matches one, the learner is told WHY it's wrong.
# --------------------------------------------------------------------------- #

TRAPS = {
    "user-usermod-group": [
        {"a": ["usermod -G {group} {user}"],
         "msg": "Careful: -G alone REPLACES the supplementary group list - "
                "{user} would be dropped from every other group. -aG appends."}],
    "lvm-lvextend": [
        {"a": ["lvextend -L 5G -r /dev/datavg/web",
               "lvextend -r -L 5G /dev/datavg/web",
               "lvextend --resizefs -L 5G /dev/datavg/web",
               "lvextend -L 5G /dev/datavg/web"],
         "msg": "-L 5G sets the LV size TO 5 GB (it could even shrink it). "
                "+5G ADDS 5 GB to the current size."},
        {"a": ["lvextend -L +5G /dev/datavg/web"],
         "msg": "That grows the LV but NOT the filesystem on it - add "
                "-r/--resizefs, or follow up with resize2fs."}],
    "proc-kill9": [
        {"a": ["kill {pid}", "kill -15 {pid}", "kill -TERM {pid}"],
         "msg": "That sends SIGTERM (15) - exactly the signal this hung "
                "process is ignoring. Signal 9 (KILL) can't be ignored."}],
    "sd-enable-now": [
        {"a": ["systemctl start sshd", "systemctl start sshd.service"],
         "msg": "start only affects the running system - after a reboot sshd "
                "stays off. The prompt wants boot persistence too."},
        {"a": ["systemctl enable sshd", "systemctl enable sshd.service"],
         "msg": "enable only takes effect at the NEXT boot - it doesn't start "
                "the service now. Add --now."}],
    "sec-firewalld-port": [
        {"a": ["firewall-cmd --add-port={port}/tcp"],
         "msg": "Runtime-only: without --permanent this rule vanishes at the "
                "next reload or reboot."}],
    "sec-setsebool": [
        {"a": ["setsebool httpd_can_network_connect on",
               "setsebool httpd_can_network_connect 1"],
         "msg": "Without -P the boolean reverts at reboot - the prompt asked "
                "for persistent."}],
    "shell-grep": [
        {"a": ["grep -r error /var/log"],
         "msg": "Recursive, yes - but case-SENSITIVE: 'Error' and 'ERROR' "
                "slip through. Add -i."},
        {"a": ["grep -i error /var/log"],
         "msg": "Case handled, but without -r grep won't descend into "
                "/var/log's subdirectories."}],
    "dev-dracut": [
        {"a": ["dracut"],
         "msg": "Without -f dracut refuses to overwrite the existing "
                "initramfs image."}],
    "fs-xfsgrow": [
        {"a": ["xfs_growfs /dev/sdc1", "xfs_growfs /dev/datavg/data"],
         "msg": "xfs_growfs takes the MOUNT POINT (/data), not the device "
                "node."}],
    "ctr-exec": [
        {"a": ["podman run -it {cname} bash", "docker run -it {cname} bash"],
         "msg": "run creates a brand-NEW container from an image - exec is "
                "what enters the RUNNING one."}],
    "log-journalctl-unit": [
        {"a": ["journalctl -u sshd", "journalctl -u sshd.service"],
         "msg": "That's the unit across ALL boots - add -b to limit it to the "
                "current boot."}],
    "ts-ss-listen": [
        {"a": ["ss -tuln", "ss -tul", "ss -lntu"],
         "msg": "Close - but without -p you can't see WHICH process owns each "
                "socket, and the prompt asks for it."}],
    "fs-mount-opts": [
        {"a": ["mount /dev/sdc1 /mnt/data"],
         "msg": "That mounts read-WRITE (the default). Add -o ro for "
                "read-only."}],
    "user-useradd": [
        {"a": ["useradd {user}"],
         "msg": "Bare useradd may skip the home directory and default to a "
                "different shell - the prompt wants -m and -s /bin/bash."}],
    "backup-tar-create": [
        {"a": ["tar -czvf /etc backup.tar.gz", "tar -czf /etc backup.tar.gz",
               "tar czf /etc backup.tar.gz", "tar czvf /etc backup.tar.gz"],
         "msg": "Argument-order trap: the archive NAME must come right after "
                "-f; sources follow. As typed, tar would try to create an "
                "archive called /etc."}],
    "sec-chmod-octal": [
        {"a": ["chmod 777 script.sh"],
         "msg": "777 'works' but hands write+execute to EVERYONE - the prompt "
                "asked for 755 (rwx r-x r-x)."}],
    "ts-iostat": [
        {"a": ["iostat"],
         "msg": "Plain iostat lacks the extended columns (%util, await) the "
                "prompt asks for - add -x."}],
    "dev-dmesg": [
        {"a": ["dmesg"],
         "msg": "Works, but timestamps stay raw seconds-since-boot - add -T "
                "for human-readable times."}],
}

# Soft-accepts: valid answers that earn a precision note instead of a fail.
SOFT = {
    "sec-ufw-allow": [
        {"a": ["ufw allow 22"],
         "msg": "Accepted - but 22/tcp is more precise; SSH doesn't need UDP "
                "22 open."}],
    "ts-free": [
        {"a": ["free -m", "free -g"],
         "msg": "Accepted - though -m/-g lock the units; -h auto-scales, "
                "which is the canonical 'human-readable' flag."}],
}


def _subst(text, vals):
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text


def instantiate(sc):
    """Return (scenario, traps, soft) with any {placeholders} randomized."""
    sid = sc["id"]
    tpl = PARAM_TEMPLATES.get(sid)
    traps = TRAPS.get(sid, [])
    soft = SOFT.get(sid, [])
    if not tpl:
        return sc, traps, soft
    blob = " ".join([tpl.get("prompt", "")] + tpl.get("accept", [])
                    + tpl.get("hints", []) + [tpl.get("explain", "")]
                    + [x for tr in traps for x in tr["a"] + [tr["msg"]]]
                    + [x for sf in soft for x in sf["a"] + [sf["msg"]]])
    keys = set(re.findall(r"\{([a-z]+)\}", blob))
    vals = {k: random.choice(PARAM_POOLS[k]) for k in keys if k in PARAM_POOLS}
    inst = dict(sc)
    inst["_vals"] = vals
    for f in ("prompt", "explain"):
        if f in tpl:
            inst[f] = _subst(tpl[f], vals)
    if "accept" in tpl:
        inst["accept"] = [_subst(a, vals) for a in tpl["accept"]]
    if "hints" in tpl:
        inst["hints"] = [_subst(h, vals) for h in tpl["hints"]]
    traps = [{"a": [_subst(a, vals) for a in tr["a"]],
              "msg": _subst(tr["msg"], vals)} for tr in traps]
    soft = [{"a": [_subst(a, vals) for a in sf["a"]],
             "msg": _subst(sf["msg"], vals)} for sf in soft]
    return inst, traps, soft


def _fam_record(prog, fam, ok):
    rec = prog.setdefault("fam", {}).setdefault(fam, [0, 0])
    rec[1] += 1
    if ok:
        rec[0] += 1


# --------------------------------------------------------------------------- #
#  Flag meanings per tool family - powers the coach-style diff feedback
#  ("Good: -t -u -l -n | Missing: -p (show owning process)") and the
#  weak-flag drills.
# --------------------------------------------------------------------------- #

FLAG_INFO = {
    "ss": {"-t": "TCP sockets", "-u": "UDP sockets", "-l": "listening only",
           "-p": "show owning process", "-n": "numeric ports",
           "-s": "summary", "-a": "all states"},
    "grep": {"-r": "recurse into dirs", "-i": "ignore case",
             "-n": "line numbers", "-l": "filenames only",
             "-v": "invert match", "-c": "count matches",
             "-E": "extended regex", "-C": "context lines"},
    "tar": {"-c": "create", "-x": "extract", "-t": "list contents",
            "-z": "gzip", "-j": "bzip2", "-J": "xz",
            "-f": "archive file", "-v": "verbose", "-C": "target dir"},
    "journalctl": {"-u": "filter by unit", "-b": "this boot", "-f": "follow",
                   "-k": "kernel only", "-p": "priority filter",
                   "-n": "last N lines", "-r": "reverse order"},
    "free": {"-h": "human-readable", "-m": "MiB", "-g": "GiB",
             "-s": "refresh interval", "-t": "total line"},
    "df": {"-h": "human-readable", "-T": "show fs type", "-i": "inodes",
           "-H": "SI units"},
    "du": {"-s": "summarize", "-h": "human-readable", "-a": "include files",
           "-d": "max depth", "--max-depth": "max depth"},
    "find": {"-name": "match filename", "-type": "entry type",
             "-size": "by size", "-mtime": "by modify age",
             "-user": "by owner", "-perm": "by permissions",
             "-empty": "empty entries", "-delete": "delete matches",
             "-4000": "the SUID bit (as a -perm value)"},
    "kill": {"-9": "SIGKILL (force)", "-15": "SIGTERM (polite)",
             "-1": "SIGHUP (reload)", "-KILL": "SIGKILL (force)",
             "-TERM": "SIGTERM (polite)", "-HUP": "SIGHUP (reload)",
             "-s": "signal by name", "-u": "by user (pkill)"},
    "useradd": {"-m": "create home dir", "-M": "no home dir",
                "-s": "login shell", "-r": "system account",
                "-G": "supplementary groups", "-a": "append (with -G)",
                "-L": "lock password", "-U": "unlock password",
                "-l": "lock (passwd)", "-u": "unlock (passwd)",
                "-e": "expiry date", "-E": "expiry date (chage)"},
    "chmod": {"-R": "recursive"},
    "chown": {"-R": "recursive"},
    "rsync": {"-a": "archive (perms/times)", "-v": "verbose",
              "-z": "compress", "-n": "dry run", "--dry-run": "dry run",
              "--delete": "mirror deletions"},
    "mount": {"-o": "options", "-t": "fs type", "-r": "read-only"},
    "podman": {"-d": "detached", "-p": "publish host:container port",
               "-i": "interactive", "-t": "allocate TTY",
               "-e": "env variable", "-v": "volume mount",
               "-a": "include stopped", "-f": "follow"},
    "firewall-cmd": {"--permanent": "persist across reloads",
                     "--reload": "apply permanent rules",
                     "--add-port": "open a port",
                     "--add-service": "open a service",
                     "--remove-port": "close a port",
                     "--list-all": "show zone config",
                     "--get-active-zones": "zones per interface"},
    "lvm": {"-L": "fixed size", "-l": "extents/percent", "-n": "LV name",
            "-r": "resize filesystem too", "--resizefs": "resize fs too"},
    "dmesg": {"-T": "human timestamps", "-w": "follow live",
              "-l": "level filter"},
    "iostat": {"-x": "extended stats", "-z": "hide idle devices",
               "-d": "devices only"},
    "vmstat": {"-s": "one-shot summary", "-w": "wide output"},
    "tcpdump": {"-i": "interface", "-w": "write pcap", "-n": "numeric",
                "-c": "packet count"},
    "mtr": {"-r": "report mode", "-c": "cycle count", "-n": "numeric",
            "-w": "wide report"},
    "modprobe": {"-r": "remove module", "-v": "verbose", "-p": "params only",
                 "-a": "all (depmod)"},
    "dracut": {"-f": "force overwrite", "--force": "force overwrite",
               "--kver": "kernel version", "-u": "update (Debian)"},
    "ssh-keygen": {"-t": "key type", "-p": "port (ssh)", "-b": "key bits"},
    "setfacl": {"-m": "modify entry", "-x": "remove entry",
                "-b": "strip all ACLs", "-R": "recursive"},
    "selinux": {"-P": "persistent", "-R": "recursive", "-v": "verbose",
                "-t": "context type", "-Z": "show contexts",
                "-a": "all booleans"},
    "crontab": {"-e": "edit", "-l": "list", "-r": "remove",
                "-u": "target user"},
    "fsck": {"-y": "auto-yes repairs", "-n": "report only", "-f": "force check"},
    "lsof": {"-i": "network sockets", "-p": "by PID", "-u": "by user"},
    "uptime": {"-p": "pretty duration", "-s": "boot timestamp"},
    "sort": {"-n": "numeric", "-r": "reverse", "-u": "unique",
             "-c": "prefix a count (uniq -c)"},
    "gzip": {"-d": "decompress", "-k": "keep original",
             "-9": "max compression"},
    "ps": {"-e": "every process", "-f": "full format", "-u": "by user",
           "--forest": "tree view"},
    "renice": {"-n": "nice value", "-p": "target PID"},
    "mkfs": {"-t": "fs type", "-L": "label"},
    "ip": {"-br": "brief output", "-brief": "brief output"},
    "ufw": {}, "systemctl": {"--now": "also start/stop immediately", "--failed": "only failed units"}, "apt": {}, "dnf": {}, "git": {"-m": "commit message", "--oneline": "one line per commit"},
    "kubectl": {"-f": "manifest file", "--replicas": "desired pod count"}, "ansible": {"-m": "module to run", "-a": "module arguments", "--check": "dry run"}, "compose": {"-d": "detached (background)"},
    "dig": {"+short": "terse answer only"},
    "chattr": {"+i": "immutable", "-i": "clear immutable",
               "+a": "append-only"},
    "fsresize": {}, "virsh": {"--all": "include powered-off VMs"}, "visudo": {"-c": "syntax check",
                                            "-f": "target file"},
    "lastb": {"-n": "row limit"}, "nohup": {},
    "systemd-analyze": {}, "lsblk": {"-f": "filesystems/UUIDs",
                                     "-p": "full device paths"},
    "ls": {"-l": "long listing", "-a": "all incl. hidden",
           "-h": "human sizes", "-R": "recursive", "-t": "sort by time"},
    "cp": {"-r": "recursive", "-R": "recursive", "-a": "archive (preserve)",
           "-p": "preserve attrs", "-i": "prompt before overwrite"},
    "rm": {"-r": "recursive", "-f": "force, no prompts",
           "-i": "prompt each file"},
    "mkdir": {"-p": "create parents"},
    "ln": {"-s": "symbolic link"},
    "cat": {"-n": "number lines"},
    "head": {"-n": "line count"},
    "tail": {"-f": "follow live", "-F": "follow + survive rotation",
             "-n": "line count"},
    "cut": {"-d": "delimiter", "-f": "field number",
            "-c": "character positions"},
    "wc": {"-l": "lines", "-w": "words", "-c": "bytes"},
    "tee": {"-a": "append"},
    "sed": {"-i": "edit in place", "-n": "suppress auto-print"},
    "awk": {"-F": "field delimiter"},
    "ping": {"-c": "probe count", "-i": "interval"},
    "traceroute": {}, "nmap": {"-p": "port range"},
    "nc": {"-v": "verbose", "-z": "scan only (no data)",
           "-l": "listen mode"},
    "curl": {"-I": "headers only (HEAD)", "-o": "output file",
             "-L": "follow redirects", "-s": "silent"},
    "nmcli": {}, "netplan": {}, "ethtool": {},
    "blkid": {}, "fdisk": {"-l": "list partition tables"},
    "parted": {"-l": "list all disks"},
    "sysctl": {"-w": "write a value", "-a": "show all"},
    "timedatectl": {}, "hostnamectl": {},
    "groupadd": {}, "getent": {}, "who": {}, "top": {},
    "umask": {}, "su": {"-": "login shell (full root env)"}, "sudo": {"-i": "root login shell",
                                    "-s": "shell, keep env",
                                    "-u": "run as user"},
    "semanage": {"-a": "add", "-t": "SELinux type", "-p": "protocol",
                 "-l": "list"},
    "iptables": {"-L": "list rules", "-n": "numeric (no DNS)",
                 "-v": "verbose counters", "-A": "append rule",
                 "-D": "delete rule", "-p": "protocol",
                 "--dport": "destination port", "-j": "jump to target"},
    "nft": {},
    "dd": {}, "bzip2": {"-d": "decompress", "-k": "keep original"},
    "xz": {"-d": "decompress", "-k": "keep original"},
    "dpkg": {"-i": "install .deb", "-l": "list installed",
             "-L": "files of a package", "-r": "remove"},
    "rpm": {"-q": "query", "-a": "all packages", "-i": "info/install",
            "-l": "list files"},
    "pip": {}, "stat": {}, "touch": {}, "mv": {}, "id": {},
    "bash-basics": {}, "redirection": {}, "less": {}, "xargs": {},
}


# --------------------------------------------------------------------------- #
#  Simulated command output - shown after a correct answer so it feels like a
#  real shell. Commands that are silent on success (chmod, kill, usermod...)
#  deliberately have NO entry: silence IS their real output.
# --------------------------------------------------------------------------- #

SIM_OUTPUT = {
    "ts-ss-listen": """Netid State  Recv-Q Send-Q Local Address:Port  Peer  Process
udp   UNCONN 0      0          0.0.0.0:53    *     users:(("systemd-resolve",pid=611,fd=13))
tcp   LISTEN 0      128        0.0.0.0:22    *     users:(("sshd",pid=812,fd=3))
tcp   LISTEN 0      511        0.0.0.0:80    *     users:(("nginx",pid=1490,fd=6))""",
    "ts-ip-addr": """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 192.168.1.40/24 brd 192.168.1.255 scope global eth0""",
    "ts-ip-route": """default via 192.168.1.1 dev eth0 proto dhcp metric 100
192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.40""",
    "ts-dig": """;; ANSWER SECTION:
example.com.        2864    IN      A       93.184.215.14

;; Query time: 18 msec
;; SERVER: 192.168.1.1#53(192.168.1.1)""",
    "ts-mtr": "(live per-hop loss/latency display opens - press q to quit)",
    "ts-tcpdump": """tcpdump: listening on eth0, link-type EN10MB (Ethernet)
14:02:11.482 IP 192.168.1.40.52814 > 93.184.215.14.443: Flags [S], length 0
14:02:11.503 IP 93.184.215.14.443 > 192.168.1.40.52814: Flags [S.], length 0
^C 2 packets captured""",
    "ts-free": """               total        used        free      shared  buff/cache   available
Mem:           7.7Gi       2.1Gi       3.4Gi       312Mi       2.2Gi       5.1Gi
Swap:          2.0Gi          0B       2.0Gi""",
    "ts-vmstat": """procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 1  0      0 3563012 142020 2174980    0    0     4    11  182  301  2  1 97  0  0""",
    "ts-iostat": """Device      r/s     w/s     rkB/s   wkB/s  await  %util
sda        4.12   11.30    88.4   412.6   1.84   2.1
sdb        0.02    0.00     0.4     0.0   0.61   0.0""",
    "ts-uptime": " 14:02:36 up 12 days,  3:41,  2 users,  load average: 0.18, 0.24, 0.21",
    "ts-journal-priority": """Jun 09 03:12:44 lab sshd[9911]: error: kex_exchange_identification: read: reset
Jun 09 07:55:02 lab kernel: EXT4-fs error (device sdb1): unable to read inode
Jun 10 11:21:18 lab nginx[1490]: [emerg] bind() to 0.0.0.0:80 failed""",
    "log-journalctl-unit": """Jun 10 08:14:02 lab sshd[812]: Server listening on 0.0.0.0 port 22.
Jun 10 09:30:51 lab sshd[4471]: Accepted publickey for marco from 10.0.0.8
Jun 10 09:30:51 lab sshd[4471]: pam_unix(sshd:session): session opened for user marco""",
    "log-journalctl-follow": """-- Journal begins, following new entries (Ctrl+C to stop) --
Jun 10 14:02:40 lab systemd[1]: Started Daily apt download activities.""",
    "sd-status": """\u25cf nginx.service - A high performance web server
     Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled)
     Active: active (running) since Tue 2026-06-09 08:14:02 UTC; 1 day ago
   Main PID: 1490 (nginx)
Jun 09 08:14:02 lab systemd[1]: Started A high performance web server.""",
    "sd-enable-now": """Created symlink /etc/systemd/system/multi-user.target.wants/sshd.service \u2192 /usr/lib/systemd/system/sshd.service.""",
    "sd-mask": "Created symlink /etc/systemd/system/bluetooth.service \u2192 /dev/null.",
    "ts-systemd-blame": """41.203s plymouth-quit-wait.service
12.844s NetworkManager-wait-online.service
 4.071s snapd.service
 1.302s dev-sda2.device""",
    "dev-lsblk": """NAME   MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda      8:0    0   100G  0 disk
\u251csda1   8:1    0     1G  0 part /boot
\u2514sda2   8:2    0    99G  0 part /
sdb      8:16   0   500G  0 disk""",
    "dev-dmesg": """[Tue Jun 10 08:13:51 2026] e1000e 0000:00:19.0 eth0: link is Up 1000 Mbps
[Tue Jun 10 08:13:52 2026] EXT4-fs (sda2): mounted filesystem with ordered data mode
[Tue Jun 10 11:40:13 2026] usb 1-2: new high-speed USB device number 4""",
    "dev-modinfo": """filename:       /lib/modules/6.8.0/kernel/drivers/net/ethernet/intel/e1000e.ko
description:    Intel(R) PRO/1000 Network Driver
license:        GPL v2
depends:        ptp""",
    "dev-dracut": "dracut: *** Creating initramfs image file '/boot/initramfs-6.8.0.img' done ***",
    "stor-blkid": """/dev/sda1: UUID="6e0c-1A2B" TYPE="vfat" PARTUUID="0001"
/dev/sda2: UUID="b1c2d3e4-5f60-4a7b-8c9d-aabbccddeeff" TYPE="ext4"
""",
    "stor-fdisk": """Disk /dev/sda: 100 GiB, 107374182400 bytes, 209715200 sectors
Device     Boot   Start       End   Sectors  Size Type
/dev/sda1  *       2048   2099199   2097152    1G Linux filesystem
/dev/sda2       2099200 209715166 207615967   99G Linux filesystem""",
    "stor-parted": """Model: ATA VBOX HARDDISK (scsi)
Disk /dev/sda: 107GB   Partition Table: gpt
 1      1049kB  1075MB  1074MB  ext4         boot
 2      1075MB  107GB   106GB   ext4""",
    "fs-df": """Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        97G   31G   62G  34% /
/dev/sda1       974M  201M  706M  23% /boot
tmpfs           3.9G     0  3.9G   0% /dev/shm""",
    "fs-du": "1.4G    /var/log",
    "fs-fsck": """fsck from util-linux 2.39
e2fsck 1.47.0: clean, 84211/6553600 files, 8123456/26214400 blocks""",
    "fs-mkfs": """mke2fs 1.47.0 (5-Feb-2023)
Creating filesystem with 26214400 4k blocks and 6553600 inodes
Writing superblocks and filesystem accounting information: done""",
    "fs-resize2fs": """resize2fs 1.47.0
The filesystem on /dev/datavg/web is now 6553600 (4k) blocks long.""",
    "fs-xfsgrow": """meta-data=/dev/mapper/datavg-data isize=512  agcount=4
data blocks changed from 2621440 to 3932160""",
    "lvm-pvcreate": '  Physical volume "/dev/sdb" successfully created.',
    "lvm-vgcreate": '  Volume group "datavg" successfully created',
    "lvm-lvcreate": '  Logical volume "{lv}" created.',
    "lvm-lvextend": """  Size of logical volume datavg/web changed from 20.00 GiB to 25.00 GiB.
  Logical volume datavg/web successfully resized.
resize2fs: The filesystem on /dev/datavg/web is now 6553600 (4k) blocks long.""",
    "backup-rsync": """sending incremental file list
data/reports/q2.xlsx
data/db/dump.sql
sent 48.21M bytes  received 1.2K bytes  9.64M bytes/sec""",
    "bk-dd": """4294967296 bytes (4.3 GB, 4.0 GiB) copied, 18 s, 239 MB/s
1024+0 records in
1024+0 records out""",
    "sw-apt-install": """Reading package lists... Done
The following NEW packages will be installed: htop
Setting up htop (3.3.0-4) ...""",
    "sw-dnf-install": """Dependencies resolved.
Installing:  httpd  x86_64  2.4.62-1.el9
Complete!""",
    "sw-dpkg": """Selecting previously unselected package agent.
Unpacking agent (1.4.2) ...
Setting up agent (1.4.2) ...""",
    "sw-rpmqa": """bash-5.2.26-1.el9.x86_64
openssh-server-8.7p1-38.el9.x86_64
httpd-2.4.62-1.el9.x86_64
kernel-5.14.0-427.el9.x86_64""",
    "sw-pip": """Collecting requests
Installing collected packages: requests
Successfully installed requests-2.32.3""",
    "user-getent": "alice:x:1001:1001::/home/alice:/bin/bash",
    "user-chage": """Last password change                    : Apr 02, 2026
Password expires                        : never
Account expires                         : never
Number of days of warning before password expires: 7""",
    "sec-restorecon": """Relabeled /var/www/html from unconfined_u:object_r:user_home_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
Relabeled /var/www/html/index.html from user_home_t to httpd_sys_content_t""",
    "sec-firewalld-port": "success",
    "sec-firewalld-reload": "success",
    "sec-ufw-allow": """Rule added
Rule added (v6)""",
    "fw-iptables": """Chain INPUT (policy ACCEPT 8412 packets, 1204K bytes)
 pkts bytes target  prot opt in  out  source     destination
 1204  72K  ACCEPT  tcp  --  *   *    0.0.0.0/0  0.0.0.0/0   tcp dpt:22""",
    "fw-nft": """table inet filter {
    chain input {
        type filter hook input priority filter; policy accept;
        tcp dport 22 accept
    }
}""",
    "sec-sshkeygen": """Generating public/private ed25519 key pair.
Enter file in which to save the key (/home/marco/.ssh/id_ed25519):
Your identification has been saved in /home/marco/.ssh/id_ed25519
The key fingerprint is: SHA256:Yk3l+f9...
""",
    "sec-find-suid": """/usr/bin/sudo
/usr/bin/passwd
/usr/bin/mount
/usr/bin/su""",
    "sec-visudo": "(sudoers opens in vi - syntax is checked when you save)",
    "sched-crontab-edit": "(your crontab opens in $EDITOR)",
    "shell-grep": """/var/log/syslog:Jun 10 11:21:18 lab nginx[1490]: [error] connect() failed
/var/log/auth.log:Jun 10 09:02:33 lab sshd[3120]: error: maximum authentication attempts
/var/log/dpkg.log.1:2026-05-28 status error linux-image-6.8.0""",
    "shell-find-size": """/var/lib/mysql/ibdata1
/var/log/journal/system.journal
/home/marco/Downloads/ubuntu-24.04.iso""",
    "shell-sort-uniq": """   412 GET /index.html HTTP/1.1
    96 GET /api/status HTTP/1.1
     3 POST /login HTTP/1.1""",
    "proc-ps": """USER   PID %CPU %MEM    VSZ   RSS TTY  STAT START  TIME COMMAND
root     1  0.0  0.3 168092 12844 ?    Ss   Jun09  0:04 /sbin/init
root   812  0.0  0.2  15436  8920 ?    Ss   Jun09  0:00 sshd: /usr/sbin/sshd
mysql 1322  0.4  9.8 1825040 392k ?    Ssl  Jun09  6:12 /usr/sbin/mysqld""",
    "proc-lsof-port": """COMMAND  PID  USER  FD  TYPE DEVICE SIZE/OFF NODE NAME
nginx   1490  root   6u IPv4  24812      0t0  TCP *:http (LISTEN)""",
    "proc-renice": "{pid} (process ID) old priority 0, new priority 10",
    "proc-nohup": """[1] 23981
nohup: ignoring input and appending output to 'nohup.out'""",
    "virt-virsh-list": """ Id   Name     State
----------------------------
 1    webvm    running
 -    buildvm  shut off""",
    "ctr-run": "9f2c1a7e44b85d3f0a6c2b91e8d7f4a5c3b2a1908f7e6d5c4b3a291807f6e5d4",
    "ctr-ps": """CONTAINER ID  IMAGE                 STATUS         PORTS                 NAMES
3fa8b2c91d04  docker.io/nginx:latest  Up 2 hours   0.0.0.0:8080->80/tcp  web
71c0de55ab12  docker.io/redis:7       Exited (0)                         cache""",
    "ctr-logs": """10.0.0.8 - - [10/Jun/2026:13:58:11 +0000] "GET / HTTP/1.1" 200 615
10.0.0.8 - - [10/Jun/2026:13:58:12 +0000] "GET /favicon.ico HTTP/1.1" 404 153""",
    "ctr-exec": "root@3fa8b2c91d04:/#",
    "ctr-build": """STEP 1/4: FROM docker.io/library/python:3.12-slim
STEP 4/4: CMD ["python", "app.py"]
COMMIT myapp:1.0
Successfully tagged localhost/myapp:1.0""",
    "ctr-prune": """3a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d
Total reclaimed space: 412MB""",
    "auto-ansible-ping": """web01 | SUCCESS => {
    "changed": false,
    "ping": "pong"
}""",
    "auto-ansible-playbook": """PLAY [all] *********************************************************
TASK [Gathering Facts] *********************************************
PLAY RECAP: web01 : ok=4  changed=1  unreachable=0  failed=0""",
    "auto-kubectl-apply": "deployment.apps/web configured",
    "auto-kubectl-scale": "deployment.apps/web scaled",
    "auto-compose-up": """[+] Running 3/3
 \u2714 Network app_default    Created
 \u2714 Container app-db-1     Started
 \u2714 Container app-web-1    Started""",
    "auto-git-commit": """[main 4f2a91c] fix deploy script
 1 file changed, 3 insertions(+), 1 deletion(-)""",
    "net-ping": """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=11.2 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=117 time=10.8 ms
--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss""",
    "net-traceroute": """traceroute to 8.8.8.8 (8.8.8.8), 30 hops max
 1  _gateway (192.168.1.1)  0.612 ms
 2  10.20.0.1 (10.20.0.1)   4.310 ms
 5  dns.google (8.8.8.8)   11.027 ms""",
    "net-nmap": """Nmap scan report for 10.0.0.5
PORT    STATE SERVICE
22/tcp  open  ssh
80/tcp  open  http
443/tcp open  https""",
    "net-nc": "Connection to web01 22 port [tcp/ssh] succeeded!",
    "net-curl": """HTTP/2 200
content-type: text/html; charset=UTF-8
cache-control: max-age=2890
server: ECAcc (dcd/7D5A)""",
    "net-nmcli": """DEVICE  TYPE      STATE      CONNECTION
eth0    ethernet  connected  Wired connection 1
lo      loopback  unmanaged  --""",
    "net-netplan": """Do you want to keep these settings?
Press ENTER before the timeout to accept the new configuration
Changes will revert in 120 seconds""",
    "net-ethtool": """Settings for eth0:
        Speed: 1000Mb/s
        Duplex: Full
        Auto-negotiation: on
        Link detected: yes""",
    "sys-timedatectl": """               Local time: Wed 2026-06-10 14:02:36 UTC
           Universal time: Wed 2026-06-10 14:02:36 UTC
                 Timezone: Etc/UTC (UTC, +0000)
System clock synchronized: yes
              NTP service: active""",
    "sys-sysctl": "net.ipv4.ip_forward = 1",
    "ts-lastb": """root     ssh:notty    203.0.113.50     Tue Jun 10 03:12 - 03:12  (00:00)
admin    ssh:notty    203.0.113.50     Tue Jun 10 03:12 - 03:12  (00:00)
root     ssh:notty    198.51.100.23    Mon Jun  9 22:41 - 22:41  (00:00)""",
    "text-head": """Jun 10 08:13:48 lab kernel: Linux version 6.8.0-39-generic
Jun 10 08:13:48 lab kernel: Command line: BOOT_IMAGE=/vmlinuz-6.8.0
... (18 more lines)""",
    "text-tailf": """Jun 10 14:02:36 lab systemd[1]: Started Session 12 of User marco.
Jun 10 14:02:40 lab CRON[24001]: (root) CMD (command -v debian-sa1)
(following - Ctrl+C to stop)""",
    "text-cut": """root
daemon
alice
marco""",
    "text-wc": "10422 access.log",
    "text-sed": """server_name example.com;
proxy_pass https://backend:8443;
return 301 https://$host$request_uri;""",
    "text-awk": """10.0.0.8
192.168.1.77
10.0.0.8""",
    "text-tee": """Deploying version 1.4.2...
Done. (output also written to deploy.log)""",
    "perm-su": "root@lab:~#",
    "perm-sudoi": "root@lab:~#",
    "backup-tar-extract": "(archive extracted to the current directory)",
    "sw-apt-install-note": "",
}



def _flag_meaning(fam, tok):
    info = FLAG_INFO.get(fam, {})
    hit = info.get(tok) or info.get(tok.split("=")[0])
    if hit:
        return hit
    if len(tok) > 2 and tok.startswith("-") and not tok.startswith("--"):
        return info.get(tok[:2])      # -d: -f1 -n50 -> -d -f -n
    return None


def flag_diff(user_cmd, accepts, fam):
    """Compare the user's command to the closest accepted form.
    Returns None if the tool itself (head) is wrong, else a diff dict."""
    utoks = normalize(user_cmd).split()
    if not utoks:
        return None
    uh, uf, uo = split_tokens(utoks)
    best = None
    bestscore = -999
    for a in accepts:
        ah, af, ao = split_tokens(normalize(a).split())
        if ah != uh:
            continue
        score = len(set(uf) & set(af)) - abs(len(uo) - len(ao))
        if score > bestscore:
            best = (af, ao)
            bestscore = score
    if best is None:
        return None
    af, ao = best
    return {
        "good": [f for f in uf if f in af],
        "missing": [f for f in af if f not in uf],
        "extra": [f for f in uf if f not in af],
        "op_missing": [o for o in ao if o not in uo],
        "op_extra": [o for o in uo if o not in ao],
        "fam": fam,
    }


def render_diff(user_cmd, diff):
    """Coach-style breakdown of what was right and what's missing."""
    fam = diff["fam"]

    def fmt(toks):
        parts = []
        for tk in toks:
            mn = _flag_meaning(fam, tk)
            parts.append(f"{tk} ({mn})" if mn else tk)
        return ", ".join(parts)

    print(f"  {d('You typed:')} {user_cmd.strip()}")
    if diff["good"]:
        print(f"  {g('Good:')}    {fmt(diff['good'])}")
    if diff["missing"]:
        print(f"  {y('Missing:')} {fmt(diff['missing'])}")
    if diff["extra"]:
        print(f"  {r('Extra:')}   {fmt(diff['extra'])} {d('(not needed here)')}")
    if diff["op_missing"]:
        print(f"  {y('Also missing:')} {', '.join(diff['op_missing'])}")
    if diff["op_extra"]:
        print(f"  {r('Not needed:')}   {', '.join(diff['op_extra'])}")


def _weak_note(prog, fam, flags):
    wf = prog.setdefault("weakflags", {}).setdefault(fam, {})
    for f in flags:
        if _flag_meaning(fam, f):
            wf[f] = wf.get(f, 0) + 1


def _weak_clear(prog, fam, used_flags):
    wf = prog.get("weakflags", {}).get(fam, {})
    for f in list(wf):
        if f in used_flags:
            wf[f] -= 1
            if wf[f] <= 0:
                del wf[f]


def micro_flag_check(fam, missing):
    """One quick remediation question on the first missing known flag."""
    target = None
    for f in missing:
        if _flag_meaning(fam, f):
            target = f
            break
    if target is None:
        return
    meaning = _flag_meaning(fam, target)
    print(f"  {m('Quick rep -')} which flag means "
          f"{b(chr(39) + meaning + chr(39))}?  {d('(:skip to pass)')}")
    ans = prompt_line(f"  {g('flag> ')}").strip()
    if ans in (":quit", ":q"):
        return "quit"
    if ans in (":menu", ":m"):
        return "menu"
    if (ans.lstrip("-+") == target.lstrip("-+") and ans
            and not ans.startswith(":")):
        print(f"  {g('● Right:')} {target}. {b('Now the full command:')}")
    else:
        print(f"  {r('●')} {y('It is')} {b(target)} {d('(' + meaning + ')')}. "
              f"{b('Now the full command:')}")
    return None






# --------------------------------------------------------------------------- #
#  Matching engine
# --------------------------------------------------------------------------- #

def normalize(s, allow_sudo=True):
    """Strip, collapse whitespace, and optionally drop a leading sudo."""
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    if allow_sudo and s.startswith("sudo "):
        s = s[5:].strip()
    return s


def split_tokens(tokens):
    """Return (head, sorted_flag_list, ordered_operand_list).

    Bundled single-letter short flags (e.g. -tulpn) are expanded so that
    flag order and bundling don't matter, while operands keep their order.
    """
    if not tokens:
        return "", [], []
    head = tokens[0]
    flags, operands = [], []
    for t in tokens[1:]:
        if len(t) > 1 and t.startswith("-"):
            if re.fullmatch(r"-[A-Za-z]{2,}", t):           # -abc -> -a -b -c
                flags.extend("-" + ch for ch in t[1:])
            else:                                            # --long, -9, -s, -o=x
                flags.append(t)
        else:
            operands.append(t)
    return head, sorted(flags), operands


def structural_match(user, accept):
    uh, uf, uo = split_tokens(user.split())
    ah, af, ao = split_tokens(accept.split())
    return uh == ah and uf == af and uo == ao


def check_answer(user_input, scenario):
    """Return True if the typed answer satisfies the scenario."""
    mode = scenario.get("mode", "smart")
    un = normalize(user_input)
    if not un:
        return False
    for accept in scenario["accept"]:
        an = normalize(accept)
        if mode == "exact":
            if un == an:
                return True
        elif mode == "regex":
            if re.fullmatch(an, un):
                return True
        elif mode == "contains":
            need = an.split()
            have = un.split()
            if all(tok in have for tok in need):
                return True
        else:  # smart
            if un == an or structural_match(un, an):
                return True
    return False


# --------------------------------------------------------------------------- #
#  Presentation helpers
# --------------------------------------------------------------------------- #

class C:
    """ANSI colors, auto-disabled when not a TTY / NO_COLOR / --no-color."""
    enabled = True
    GREEN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"; CYAN = "\033[96m"
    DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"; MAG = "\033[95m"

    @classmethod
    def wrap(cls, code, text):
        return f"{code}{text}{cls.RESET}" if cls.enabled else text


def g(t): return C.wrap(C.GREEN, t)
def r(t): return C.wrap(C.RED, t)
def y(t): return C.wrap(C.YEL, t)
def c(t): return C.wrap(C.CYAN, t)
def d(t): return C.wrap(C.DIM, t)
def b(t): return C.wrap(C.BOLD, t)
def m(t): return C.wrap(C.MAG, t)


def ok(t): return g("\u25cf " + t)     # green dot + green text
def bad(t): return r("\u25cf " + t)    # red dot + red text


CLEAR_OK = [True]   # disabled by --no-clear or when output is piped


def clear_screen():
    if CLEAR_OK[0]:
        print("\033[2J\033[H", end="")


BANNER = r"""
███████╗███████╗██████╗  ██████╗ ██████╗ ███████╗██████╗
╚══███╔╝██╔════╝██╔══██╗██╔═████╗██╔══██╗██╔════╝██╔══██╗
  ███╔╝ █████╗  ██████╔╝██║██╔██║██████╔╝█████╗  ██║  ██║
 ███╔╝  ██╔══╝  ██╔══██╗████╔╝██║██╔══██╗██╔══╝  ██║  ██║
███████╗███████╗██║  ██║╚██████╔╝██║  ██║███████╗██████╔╝
╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═════╝"""


# --------------------------------------------------------------------------- #
#  Progress (Leitner-style spaced repetition)
# --------------------------------------------------------------------------- #

PROGRESS_PATH = os.path.expanduser("~/.linuxplus_cmd_trainer.json")


def load_progress(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"boxes": {}, "seen": 0, "correct": 0, "first_try": 0}


def save_progress(path, prog):
    try:
        with open(path, "w") as f:
            json.dump(prog, f, indent=2)
    except Exception:
        pass  # never let a save failure interrupt studying


def box_of(prog, sid):
    return prog["boxes"].get(sid, 0)  # 0 = never answered correctly


def weighted_pick(scenarios, prog, exclude=None):
    """Pick a scenario, favoring ones in low Leitner boxes (less mastered)."""
    pool = [s for s in scenarios if s["id"] != exclude] or scenarios
    weights = [max(1, 6 - box_of(prog, s["id"])) for s in pool]
    return random.choices(pool, weights=weights, k=1)[0]


# --------------------------------------------------------------------------- #
#  Session
# --------------------------------------------------------------------------- #

DOMAINS = sorted({s["domain"] for s in SCENARIOS})

HELP_TEXT = f"""
{b('Commands you can type instead of an answer:')}
  {c(':hint')}     reveal the next hint (small first, bigger later)
  {c(':answer')}   give up and show the correct command
  {c(':skip')}     skip to a new scenario
  {c(':stats')}    show your progress
  {c(':menu')}     change which domain you're drilling
  {c(':level')}    switch difficulty (tutorial / practice / exam)
  {c(':help')}     show this help
  {c(':quit')}     save and exit
"""


def prompt_line(text=""):
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        return ":quit"


def choose_domain():
    print(f"\n{b('What would you like to drill?')}")
    print(f"  {c('0')}  Everything (all domains)")
    for i, dom in enumerate(DOMAINS, 1):
        n = sum(1 for s in SCENARIOS if s["domain"] == dom)
        print(f"  {c(str(i))}  {dom}  {d('(' + str(n) + ' scenarios)')}")
    print(f"  {c('w')}  Weak spots only {d('(the ones you keep missing)')}")
    while True:
        choice = prompt_line(f"\n{g('select> ')}").strip().lower()
        if choice == ":quit":
            return None, None
        if choice == "w":
            return "weak", None
        if choice == "0" or choice == "":
            return "all", None
        if choice.isdigit() and 1 <= int(choice) <= len(DOMAINS):
            return "domain", DOMAINS[int(choice) - 1]
        print(r("  Please pick a number from the list (or 'w')."))


DIFF_LABELS = {"learn": "Learn", "tutorial": "Tutorial",
               "practice": "Practice", "exam": "Exam"}


def choose_difficulty():
    print(f"\n{b('Pick a difficulty:')}")
    print(f"  {c('1')}  Learn     "
          f"{d('- shows the answer; you copy it to build the pattern')}")
    print(f"  {c('2')}  Tutorial  "
          f"{d('- explains tool + flags, then rep-drills it until YOU move on')}")
    print(f"  {c('3')}  Practice  {d('- scenario + hints on demand (default)')}")
    print(f"  {c('4')}  Exam      {d('- scenario only, no hints, no scaffolding')}")
    while True:
        choice = prompt_line(f"\n{g('level> ')}").strip().lower()
        if choice == ":quit":
            return None
        if choice in ("1", "learn", "copy"):
            return "learn"
        if choice in ("2", "tutorial", "t"):
            return "tutorial"
        if choice in ("", "3", "practice", "p"):
            return "practice"
        if choice in ("4", "exam", "e"):
            return "exam"
        print(r("  Pick 1-4."))


def derive_tool(sc):
    tt = TEACH.get(sc["id"], {})
    return tt.get("tool_label") or sc["accept"][0].split()[0]


def render_teach(sc, ask=True):
    """Print the Tutorial briefing for a scenario."""
    tt = TEACH.get(sc["id"], {})
    print(f"  {m('--- TUTORIAL ' + '-' * 50)}")
    print(f"  {b('Tool:')}  {c(derive_tool(sc))}")

    why = tt.get("why") or sc["explain"]
    wrapped = textwrap.wrap(why, width=66)
    print(f"  {b('Why:')}   {wrapped[0] if wrapped else why}")
    for line in wrapped[1:]:
        print(f"         {line}")

    flags = tt.get("flags")
    if not flags:  # fall back to flags visible in the canonical answer
        _, found, _ = split_tokens(sc["accept"][0].split())
        if found:
            print(f"  {b('Flags:')} {', '.join(found)}"
                  f"{d('   (type :hint for what each does)')}")
    else:
        print(f"  {b('Flags:')}")
        for fname, fdesc in flags:
            pad = " " * max(1, 16 - len(fname))
            print(f"      {c(fname)}{pad}{fdesc}")

    if tt.get("target"):
        print(f"  {b('Target:')} {tt['target']}")
    print(f"  {m('-' * 63)}")
    if ask:
        print(f"  {b('Now write the command.')}")


def run_drill(dr, prog, tool, rep):
    """One rep exercise. Returns 'ok' (back to rep prompt) or quit/menu/level."""
    pseudo = {"accept": dr["a"], "mode": dr.get("m", "smart")}
    print(f"\n  {d('─' * 56)}")
    print(f"  {m('rep ' + str(rep))} {d('on')} {c(tool)}")
    print(f"  {c('>>')} {b('Task:')} {dr['q']}")
    while True:
        ans = prompt_line(f"  {g('$ ')}").strip()
        if not ans:
            continue
        if ans in (":quit", ":q"):
            return "quit"
        if ans in (":menu",):
            return "menu"
        if ans in (":level", ":l"):
            return "level"
        if ans in (":stats", ":s"):
            show_stats(prog)
            continue
        if ans in (":hint", ":h"):
            hint = dr.get("h") or ("it starts with: " + dr["a"][0].split()[0])
            print(f"  {y('hint:')} {hint}")
            continue
        if ans in (":skip", ":n", ":answer", ":a", ":reveal"):
            print(f"  {y('Answer:')} {b(dr['a'][0])}")
            if dr.get("e"):
                print(f"  {d(dr['e'])}")
            prog["drill_reps"] = prog.get("drill_reps", 0) + 1
            _fam_record(prog, tool, False)
            return "ok"
        if check_answer(ans, pseudo):
            prog["drill_reps"] = prog.get("drill_reps", 0) + 1
            prog["drill_correct"] = prog.get("drill_correct", 0) + 1
            _fam_record(prog, tool, True)
            print()
            print(f"{g('user@lab')}{d(':')}{c('~')}{d('$')} {ans}")
            print()
            print(f"  {g('● Correct answer.')}")
            if dr.get("e"):
                print()
                print(f"  {d(dr['e'])}")
            return "ok"
        _fam_record(prog, tool, False)
        diff = flag_diff(ans, dr["a"], tool)
        print(f"  {r('● Not quite.')}")
        if diff:
            render_diff(ans, diff)
            _weak_note(prog, tool, diff["missing"])
        print(f"  {d('Try again, or :hint / :answer')}")
        print(f"\n  {c('>>')} {b('Task:')} {dr['q']}")


def drill_loop(sc, prog):
    """Tutorial rep mode: keep serving exercises on the same tool until the
    learner moves on. Returns 'next', 'menu', 'level', or 'quit'."""
    tool = drill_key(sc)
    bank = DRILLS.get(tool, [])
    order = list(range(len(bank)))
    random.shuffle(order)
    idx = 0
    rep = 0
    extra = "" if bank else d(" (re-typing from memory - repetition still counts!)")
    print(f"\n{d('─' * 70)}")
    print(f"  {b('Rep it in:')} keep drilling {c(tool)} until it sticks.{extra}")
    print(d("  [Enter] another rep    [n] next scenario    "
            "(:menu / :level / :quit also work)"))
    while True:
        choice = prompt_line(f"{g('rep> ')}").strip().lower()
        if choice in ("n", "next", ":n", ":skip", ":next"):
            return "next"
        if choice in (":quit", ":q"):
            return "quit"
        if choice in (":menu", ":m"):
            return "menu"
        if choice in (":level", ":l"):
            return "level"
        if choice in (":stats", ":s"):
            show_stats(prog)
            continue
        if choice not in ("", "y", "r", "rep", ":rep"):
            print(d("  Press Enter for another rep, or n to move on."))
            continue
        rep += 1
        clear_screen()
        if bank:
            dr = bank[order[idx]]
            idx += 1
            if idx >= len(order):           # cycled through them all -
                idx = 0                     # reshuffle and keep going
                random.shuffle(order)
        else:
            # no authored drills for this tool: re-type the original from memory
            dr = {"q": "From memory, write it again: " + sc["prompt"],
                  "a": sc["accept"], "e": sc["explain"],
                  "m": sc.get("mode", "smart"),
                  "h": sc["hints"][-1] if sc.get("hints") else None}
        res = run_drill(dr, prog, tool, rep)
        if res != "ok":
            return res


def filter_scenarios(kind, value, prog):
    if kind == "domain":
        return [s for s in SCENARIOS if s["domain"] == value]
    if kind == "weak":
        weak = [s for s in SCENARIOS if box_of(prog, s["id"]) <= 2]
        return weak if weak else SCENARIOS
    return SCENARIOS


def show_stats(prog):
    seen, correct = prog.get("seen", 0), prog.get("correct", 0)
    first = prog.get("first_try", 0)
    acc = (correct / seen * 100) if seen else 0
    mastered = sum(1 for v in prog["boxes"].values() if v >= 5)
    touched = len(prog["boxes"])
    print(f"\n{b('=== Your progress ===')}")
    print(f"  Scenarios attempted : {c(str(seen))}")
    print(f"  Correct             : {g(str(correct))}  "
          f"({acc:.0f}% of attempts)")
    print(f"  Solved on first try : {g(str(first))}")
    print(f"  Mastered (box 5/5)  : {g(str(mastered))} of {len(SCENARIOS)}")
    reps = prog.get("drill_reps", 0)
    if reps:
        rok = prog.get("drill_correct", 0)
        print(f"  Tutorial reps       : {g(str(rok))}/{c(str(reps))} correct")
    print(f"  Unique seen         : {c(str(touched))} of {len(SCENARIOS)}")
    # per-domain mastery bar
    print(f"\n  {b('By domain (mastered / total):')}")
    for dom in DOMAINS:
        ids = [s["id"] for s in SCENARIOS if s["domain"] == dom]
        done = sum(1 for sid in ids if box_of(prog, sid) >= 5)
        total = len(ids)
        filled = int((done / total) * 20) if total else 0
        bar = g("#" * filled) + d("-" * (20 - filled))
        print(f"    {dom[:42]:42} [{bar}] {done}/{total}")
    famrec = prog.get("fam", {})
    rows = [(k, v[0], v[1]) for k, v in famrec.items() if v[1] >= 3]
    if rows:
        rows.sort(key=lambda x: x[1] / x[2])
        print(f"\n  {b('Accuracy by command family (weakest first):')}")
        for k, ok, tot in rows[:10]:
            pct = ok / tot * 100
            col = r if pct < 60 else (y if pct < 85 else g)
            print(f"    {k:16} {col(format(pct, '3.0f') + '%')}  ({ok}/{tot})")
    print()


def _toolmode(prog, fam):
    return prog.setdefault("toolmode", {}).setdefault(
        fam, {"learn": 0, "guided": [0, 0], "exam": [0, 0]})


def ask_scenario(sc, prog, difficulty="practice"):
    """Run one scenario to completion. Returns 'done','next','menu','level','quit'."""
    sc, traps, soft = instantiate(sc)
    fam = drill_key(sc)
    tm = _toolmode(prog, fam)
    bucket = "exam" if difficulty == "exam" else "guided"
    print("\n" + "-" * 70)
    print(f"{d(sc['domain'])}  {d('|')}  {c(sc['topic'])}  "
          f"{d('|  obj ' + sc.get('obj', '?'))}  "
          f"{d('. ' + DIFF_LABELS[difficulty])}")
    print(f"\n{c('>>')} {b('Scenario:')} {sc['prompt']}\n")
    if difficulty in ("tutorial", "learn"):
        render_teach(sc)
        print()
    if difficulty == "learn":
        print(f"  {b('Copy it to build the pattern:')}  {c(sc['accept'][0])}\n")
    def _remind():
        print(f"\n  {c('>>')} {b('Task:')} {sc['prompt']}")

    hint_idx = 0
    first_attempt = True
    solved_clean = True
    did_micro = False
    box_cap = {"learn": 1, "tutorial": 3}.get(difficulty, 5)

    while True:
        ans = prompt_line(f"{g('$ ')}")
        cmd = ans.strip()

        if not cmd:
            continue
        if cmd in (":quit", ":q"):
            return "quit"
        if cmd in (":menu", ":m"):
            return "menu"
        if cmd in (":level", ":l"):
            return "level"
        if cmd in (":help", ":h", "?"):
            print(HELP_TEXT)
            continue
        if cmd in (":stats", ":s"):
            show_stats(prog)
            continue
        if cmd in (":skip", ":n"):
            print(d(f"  (skipped - the answer was: {sc['accept'][0]})"))
            return "next"
        if cmd in (":hint",):
            if difficulty == "exam":
                print(d("  Hints are off in Exam mode. Answer it, "
                        "or :answer to reveal / :skip to pass."))
                continue
            solved_clean = False
            if hint_idx < len(sc["hints"]):
                print(f"  {y('hint ' + str(hint_idx + 1) + ':')} "
                      f"{sc['hints'][hint_idx]}")
                hint_idx += 1
            else:
                print(d("  No more hints - type :answer to reveal it."))
            continue
        if cmd in (":answer", ":a", ":reveal"):
            solved_clean = False
            print(f"  {y('Answer:')} {b(sc['accept'][0])}")
            print()
            print(f"  {d(sc['explain'])}")
            prog["seen"] = prog.get("seen", 0) + 1
            if difficulty != "learn":
                tm[bucket][1] += 1
            return "next"

        # --- answer attempt ---
        hit = check_answer(cmd, sc)
        soft_hit = None
        if not hit:
            for sf in soft:
                if check_answer(cmd, {"accept": sf["a"], "mode": "smart"}):
                    soft_hit = sf
                    hit = True
                    break
        if hit:
            _, used_flags, _ = split_tokens(normalize(cmd).split())
            _weak_clear(prog, fam, used_flags)
            print()
            print(f"{g('user@lab')}{d(':')}{c('~')}{d('$')} {cmd}")
            _sim = SIM_OUTPUT.get(sc["id"])
            if _sim:
                vals = sc.get("_vals")
                if vals:
                    _sim = _subst(_sim, vals)
                print(_sim)
            if difficulty == "learn":
                tm["learn"] += 1
                print()
                print(f"  {g('● Good copy.')}")
                print()
                print(f"  {d(sc['explain'])}")
                return "done"
            prog["seen"] = prog.get("seen", 0) + 1
            prog["correct"] = prog.get("correct", 0) + 1
            _fam_record(prog, fam, True)
            tm[bucket][1] += 1
            tm[bucket][0] += 1
            if first_attempt and solved_clean:
                prog["first_try"] = prog.get("first_try", 0) + 1
                prog["boxes"][sc["id"]] = min(box_cap, box_of(prog, sc["id"]) + 1)
                tag = g("● Correct answer - first try! ")
                if box_of(prog, sc["id"]) >= 5:
                    tag += m("(mastered)")
            else:
                prog["boxes"][sc["id"]] = min(2, box_of(prog, sc["id"]) + 1)
                tag = g("● Correct answer.")
            print()
            print(f"  {tag}")
            if soft_hit:
                print(f"  {y('Note:')} {soft_hit['msg']}")
            print()
            print(f"  {d(sc['explain'])}")
            return "done"

        # --- wrong ---
        first_attempt = False
        if difficulty == "learn":
            diff = flag_diff(cmd, sc["accept"], fam)
            print(f"  {r('● Not quite - it is right above you, no pressure.')}")
            if diff:
                render_diff(cmd, diff)
            continue
        _fam_record(prog, fam, False)
        tm[bucket][1] += 1
        prog["boxes"][sc["id"]] = 1
        trap_msg = None
        for tr in traps:
            if check_answer(cmd, {"accept": tr["a"], "mode": "smart"}):
                trap_msg = tr["msg"]
                break
        if trap_msg:
            print(f"  {r('● Not quite.')} {y(trap_msg)}")
            _remind()
            continue
        if difficulty == "exam":
            print(f"  {r('● Not quite.')} {d('Try again, or :answer / :skip')}")
            _remind()
            continue
        diff = flag_diff(cmd, sc["accept"], fam)
        print(f"  {r('● Not quite.')}")
        if diff is None:
            print(d("  Different tool - re-read what the scenario is asking for."))
        else:
            render_diff(cmd, diff)
            _weak_note(prog, fam, diff["missing"])
            if diff["missing"] and not did_micro:
                did_micro = True
                mres = micro_flag_check(fam, diff["missing"])
                if mres in ("quit", "menu"):
                    return mres
                _remind()
                continue
        print(f"  {d('Try again, or :hint / :answer / :skip')}")
        _remind()


# --------------------------------------------------------------------------- #
#  Gym modes: learn-a-tool, weak-flag drills, mastery report, weak-tool picker
# --------------------------------------------------------------------------- #

def fam_scenarios(fam):
    return [s for s in SCENARIOS if drill_key(s) == fam]


def exam_ready(prog, fam):
    tm = prog.get("toolmode", {}).get(fam)
    if not tm:
        return False
    gok, gtot = tm["guided"]
    eok, etot = tm["exam"]
    wf = prog.get("weakflags", {}).get(fam, {})
    return (gtot >= 10 and gok / gtot >= 0.8 and not wf
            and etot >= 5 and eok / etot >= 0.8)


def tool_report(prog):
    tms = prog.get("toolmode", {})
    print(f"\n{b('=== Tool mastery ===')}")
    if not tms:
        print(d("  Nothing tracked yet - answer a few scenarios first.\n"))
        return
    rows = []
    for fam, tm in tms.items():
        gok, gtot = tm["guided"]
        eok, etot = tm["exam"]
        wf = sorted(prog.get("weakflags", {}).get(fam, {}))
        gp = (gok / gtot * 100) if gtot else 0.0
        rows.append((gp, fam, gok, gtot, eok, etot, wf,
                     exam_ready(prog, fam), tm["learn"]))
    rows.sort()
    for gp, fam, gok, gtot, eok, etot, wf, ready, lrn in rows:
        col = r if gtot and gp < 60 else (y if gtot and gp < 85 else g)
        gtxt = col(f"{gok}/{gtot}") if gtot else d("0/0")
        etxt = f"{eok}/{etot}" if etot else d("-")
        wtxt = r(",".join(wf)) if wf else g("none")
        rtxt = g("YES") if ready else d("not yet")
        print(f"  {fam:14} learn {lrn:2}  guided {gtxt:>14}  exam {etxt:>5}  "
              f"weak flags: {wtxt}  exam-ready: {rtxt}")
    print()


def pick_weak_family(prog):
    """The family most in need of work."""
    cands = [(v[0] / v[1], v[1], k) for k, v in prog.get("fam", {}).items()
             if v[1] >= 4]
    if cands:
        cands.sort()
        if cands[0][0] < 0.95:
            return cands[0][2]
    wfs = {k: sum(v.values()) for k, v in prog.get("weakflags", {}).items() if v}
    if wfs:
        return max(wfs, key=wfs.get)
    return None


TOOL_CATS = [
    ("System Management", [
        ("Files & navigation", ["cp", "rm", "mkdir", "ln"]),
        ("Text tools", ["head", "tail", "grep", "cut", "sort", "wc",
                        "tee", "xargs", "sed", "awk", "find"]),
        ("Shell & redirection", ["redirection"]),
        ("Storage & mounting", ["lsblk", "blkid", "fdisk", "parted", "mkfs",
                                "mount", "df", "du", "fsck", "fsresize"]),
        ("LVM", ["lvm"]),
        ("Devices & kernel", ["modprobe", "dmesg", "dracut"]),
        ("Networking tools", ["ip", "ss", "ping", "dig", "mtr", "traceroute",
                              "tcpdump", "nmap", "nc", "curl", "nmcli",
                              "netplan", "ethtool"]),
        ("Backup & compression", ["tar", "gzip", "bzip2", "xz", "rsync", "dd"]),
        ("Virtualization", ["virsh"]),
    ]),
    ("Services & User Management", [
        ("systemd & services", ["systemctl", "systemd-analyze"]),
        ("Logs (journald)", ["journalctl"]),
        ("System settings", ["timedatectl", "hostnamectl", "sysctl"]),
        ("Processes & jobs", ["ps", "kill", "renice", "nohup", "lsof",
                              "crontab"]),
        ("Users & groups", ["useradd", "groupadd", "getent"]),
        ("Packages", ["apt", "dnf", "dpkg", "rpm", "pip"]),
        ("Containers", ["podman"]),
    ]),
    ("Security", [
        ("Permissions & ownership", ["chmod", "chown", "umask", "su", "sudo"]),
        ("ACLs & attributes", ["setfacl", "chattr"]),
        ("SELinux", ["selinux", "semanage"]),
        ("Firewalls", ["firewall-cmd", "ufw", "iptables", "nft"]),
        ("SSH & sudoers", ["ssh-keygen", "visudo"]),
        ("Login auditing", ["lastb"]),
    ]),
    ("Automation & Scripting", [
        ("Shell scripting basics", ["bash-basics"]),
        ("Git", ["git"]),
        ("Ansible / K8s / Compose", ["ansible", "kubectl", "compose"]),
    ]),
    ("Troubleshooting", [
        ("Performance & resources", ["free", "vmstat", "iostat", "uptime"]),
    ]),
]


def _pick_numbered(title, items, render):
    """Generic numbered menu with 0 = back. Returns item or None (back/quit)."""
    print(f"\n{b(title)}   {d('(0 = back)')}")
    for i, it in enumerate(items, 1):
        print(f"  {c(str(i))}  {render(it)}")
    print(f"  {c('0')}  Back")
    while True:
        ch = prompt_line(f"\n{g('> ')}").strip().lower()
        if ch in (":quit", ":q"):
            return ":quit"
        if ch in (":menu", ":m"):
            return ":mainmenu"
        if ch in ("0", "b", "back"):
            return None
        if ch.isdigit() and 1 <= int(ch) <= len(items):
            return items[int(ch) - 1]
        print(r("  Pick a number from the list (0 to go back)."))


def learn_tool(prog):
    """Learn Mode: category -> topic -> tool -> intro + copy reps + guided."""
    touched = set(prog.get("fam", {}))
    while True:
        cat = _pick_numbered("GYM - pick a category:", TOOL_CATS, lambda x: x[0])
        if cat == ":quit":
            return "quit"
        if cat is None or cat == ":mainmenu":
            return "menu"
        catname, subs = cat
        while True:
            sub = _pick_numbered(
                f"{catname} - pick a topic:", subs,
                lambda x: f"{x[0]}  {d('(' + str(len(x[1])) + ' tools)')}")
            if sub == ":quit":
                return "quit"
            if sub == ":mainmenu":
                return "menu"
            if sub is None:
                break  # back to categories
            subname, fams = sub
            fams = [f for f in fams if fam_scenarios(f)]
            while True:
                def _tline(f):
                    n = len(fam_scenarios(f))
                    mark = d("  · started") if f in touched else ""
                    return f"{f}  {d('(' + str(n) + ' scenarios)')}{mark}"
                fam = _pick_numbered(f"{subname} - pick a tool:", fams, _tline)
                if fam == ":quit":
                    return "quit"
                if fam == ":mainmenu":
                    return "menu"
                if fam is None:
                    break  # back to topics
                res = _run_learn_flow(fam, prog)
                if res in ("quit", "menu"):
                    return res
                touched = set(prog.get("fam", {}))


def _learn_examples(fam):
    """Goal/command/why triples: the tool's scenarios + its drill variations."""
    items = []
    for s in fam_scenarios(fam)[:2]:
        inst, _, _ = instantiate(s)
        items.append((inst["prompt"], inst["accept"][0], inst.get("explain")))
    for dr in DRILLS.get(fam, [])[:3]:
        items.append((dr["q"], dr["a"][0], dr.get("e")))
    # drop duplicate commands (a drill can mirror a scenario)
    seen, out = set(), []
    for goal, cmd, why in items:
        key = normalize(cmd)
        if key in seen:
            continue
        seen.add(key)
        out.append((goal, cmd, why))
    return out[:4]


def _run_learn_flow(fam, prog):
    pool = fam_scenarios(fam)
    sc0, _, _ = instantiate(pool[0])
    print(f"\n{b('=== Learning: ' + fam + ' ===')}")
    render_teach(sc0, ask=False)
    tm = _toolmode(prog, fam)
    examples = _learn_examples(fam)
    total = len(examples)
    for i, (goal, cmd, why) in enumerate(examples, 1):
        print(f"\n  {d('─' * 56)}")
        print(f"  {m('Example ' + str(i) + ' of ' + str(total))}")
        print(f"  {c('>>')} {b('Goal:')} {goal}")
        print(f"  {b('How:')}  {c(cmd)}")
        flags = [tok for tok in normalize(cmd).split()[1:]
                 if tok.startswith("-") or tok.startswith("+")]
        for fl in flags:
            mn = _flag_meaning(fam, fl)
            pad = " " * max(2, 14 - len(fl))
            line = f"          {c(fl)}{pad}"
            if mn:
                line += d("-> " + mn)
            print(line)
        if why:
            print(f"  {d('Result: ' + why)}")
        print(f"  {b('Type it to lock it in:')}")
        while True:
            ans = prompt_line(f"  {g('$ ')}").strip()
            if not ans:
                continue
            if ans in (":quit", ":q"):
                return "quit"
            if ans in (":menu", ":m"):
                return "menu"
            if ans in (":skip", ":n"):
                break
            if check_answer(ans, {"accept": [cmd], "mode": "smart"}):
                tm["learn"] += 1
                print(f"  {ok('Got it.')}")
                break
            diff = flag_diff(ans, [cmd], fam)
            print(f"  {bad('Almost - the command is right above.')}")
            if diff:
                render_diff(ans, diff)
    print(f"\n  {b('Now from memory - same tool, no answer shown:')}")
    return study_loop(pool, "tutorial", prog, session_len=5,
                      label=f"learning {fam}")


def weak_flag_drill(prog):
    """Rapid-fire: which flag means X? Clears weak-flag debt."""
    items = [(fam, fl) for fam, d_ in prog.get("weakflags", {}).items()
             for fl in d_]
    if not items:
        print(g("\n  No weak flags right now - nicely done. "
                "Misses will land here automatically.\n"))
        return "menu"
    random.shuffle(items)
    print(f"\n{b('Weak-flag drill')} {d('- ' + str(len(items)) + ' to clear. Enter answers, :menu to stop.')}")
    qn = 0
    for fam, fl in items[:10]:
        meaning = _flag_meaning(fam, fl)
        if not meaning:
            continue
        qn += 1
        print(f"\n  {c(str(qn))}. In {b(fam)}, which flag means "
              f"{b(chr(39) + meaning + chr(39))}?")
        ans = prompt_line(f"  {g('flag> ')}").strip()
        if ans in (":quit", ":q"):
            return "quit"
        if ans in (":menu", ":m"):
            return "menu"
        if ans and ans.lstrip("-+") == fl.lstrip("-+"):
            print(f"  {g('● Right:')} {fl}")
            _weak_clear(prog, fam, [fl])
        else:
            print(f"  {r('●')} {y('It is')} {b(fl)} - {meaning}")
            _weak_note(prog, fam, [fl])
    left = sum(len(v) for v in prog.get("weakflags", {}).values())
    print(f"\n  {g('Drill done.')} {d(str(left) + ' weak-flag reps still owed.')}")
    return "menu"


def study_loop(pool, difficulty, prog, session_len=8, label=""):
    """Core loop with finishable session checkpoints."""
    last_id = None
    answered = 0
    start_correct = prog.get("correct", 0)
    clear_screen()
    while True:
        sc = weighted_pick(pool, prog, exclude=last_id if len(pool) > 1 else None)
        last_id = sc["id"]
        result = ask_scenario(sc, prog, difficulty)
        if result == "done" and difficulty in ("tutorial", "learn"):
            result = drill_loop(sc, prog)
        if result in ("quit", "menu"):
            return result
        if result == "level":
            new = choose_difficulty()
            if new is None:
                return "quit"
            difficulty = new
            print(d(f"\n  Switched to {DIFF_LABELS[difficulty]} mode."))
            continue
        answered += 1
        if answered % session_len == 0:
            got = prog.get("correct", 0) - start_correct
            print(f"\n  {m('--- Session checkpoint ---')}")
            print(f"  {b(str(answered) + ' scenarios')} this session, "
                  f"{g(str(got) + ' correct')}"
                  + (f"  {d('(' + label + ')')}" if label else ""))
            print(d("  [Enter] keep going    [m] main menu    [:quit] save & exit"))
            ch = prompt_line(f"{g('> ')}").strip().lower()
            if ch in (":quit", ":q"):
                return "quit"
            if ch in ("m", ":menu", ":m"):
                return "menu"
            clear_screen()
        else:
            print(d("\n  [Enter] next question    [m] menu    [:quit] save & exit"))
            ch = prompt_line(f"{g('> ')}").strip().lower()
            if ch in (":quit", ":q"):
                return "quit"
            if ch in ("m", ":menu", ":m"):
                return "menu"
            clear_screen()


def main_menu(prog):
    print(f"\n{b('What do you want to do?')}")
    print(f"  {c('1')}  GYM mode             "
          f"{d('(learn & drill tools by category)')}")
    print(f"  {c('2')}  Scenario practice    "
          f"{d('(pick a domain, hints on demand)')}")
    print(f"  {c('3')}  Mixed exam mode      {d('(everything, no scaffolding)')}")
    print(f"  {c('4')}  Progress")
    print(f"  {c('q')}  Save and quit")
    while True:
        ch = prompt_line(f"\n{g('menu> ')}").strip().lower()
        if ch in ("q", ":quit", ":q"):
            return "quit"
        if ch in ("1", "2", "3", "4"):
            return ch
        print(r("  Pick 1-4 or q."))


def run():
    # ---- args ----
    args = sys.argv[1:]
    if "--version" in args or "-V" in args:
        print(f"Zer0red Linux+ trainer v{__version__}")
        return
    progress_path = PROGRESS_PATH
    if "--no-color" in args or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        C.enabled = False
    CLEAR_OK[0] = sys.stdout.isatty() and "--no-clear" not in args
    if "--progress" in args:
        i = args.index("--progress")
        if i + 1 < len(args):
            progress_path = os.path.expanduser(args[i + 1])
    if "--reset" in args:
        try:
            os.remove(progress_path)
        except OSError:
            pass

    prog = load_progress(progress_path)

    def opt(name):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    session_len = 8
    if opt("--session") and opt("--session").isdigit():
        session_len = max(3, int(opt("--session")))
    cli_level = opt("--level")
    if cli_level is not None and cli_level not in DIFF_LABELS:
        print(r(f"Unknown --level '{cli_level}' (learn/tutorial/practice/exam)"))
        cli_level = None
    pool = None
    pool_desc = ""
    topic = opt("--topic")
    objective = opt("--objective")
    if "--weak" in args:
        pool = filter_scenarios("weak", None, prog)
        pool_desc = "weak spots"
    elif topic:
        tl = topic.lower()
        pool = [s for s in SCENARIOS
                if drill_key(s) == tl or tl == s["topic"].lower()
                or (len(tl) >= 4 and tl in s["topic"].lower())]
        pool_desc = f"topic '{topic}'"
    elif objective:
        pool = [s for s in SCENARIOS if s.get("obj", "").startswith(objective)]
        pool_desc = f"objective {objective}"
    if pool is not None and not pool:
        print(r(f"  No scenarios match {pool_desc} - opening the menu."))
        pool = None

    print(r(BANNER))
    print(c(f"  CompTIA Linux+ XK0-006  *  Command Gym  *  v{__version__}"))
    print(d("  Nothing you type is executed. This only checks your answer against"))
    print(d("  the expected command, so practice freely - your system is untouched."))
    print(HELP_TEXT)
    print(d("  CLI: --weak | --topic <tool> | --objective <N.N> | "
            "--level <mode> | --session <N>"))

    def bye():
        save_progress(progress_path, prog)
        show_stats(prog)
        print(g("Progress saved to ") + d(progress_path))
        print(g("Keep at it - see you next session.\n"))

    # CLI fast path: jump straight into a study loop
    if pool is not None:
        difficulty = cli_level or choose_difficulty()
        if difficulty is None:
            bye()
            return
        print(d(f"\n  Pool: {pool_desc} ({len(pool)} scenarios) - "
                f"{DIFF_LABELS[difficulty]} mode"))
        res = study_loop(pool, difficulty, prog, session_len, pool_desc)
        save_progress(progress_path, prog)
        if res == "quit":
            bye()
            return
        # fall through to the menu on :menu

    while True:
        choice = main_menu(prog)
        save_progress(progress_path, prog)
        if choice == "quit":
            bye()
            return
        if choice == "1":
            res = learn_tool(prog)
        elif choice == "2":
            difficulty = cli_level or "practice"
            kind, value = choose_domain()
            if kind is None:
                res = "quit"
            else:
                res = study_loop(filter_scenarios(kind, value, prog),
                                 difficulty, prog, session_len)
        elif choice == "3":
            res = study_loop(SCENARIOS, "exam", prog, session_len, "mixed exam")
        else:
            show_stats(prog)
            tool_report(prog)
            res = "menu"
        save_progress(progress_path, prog)
        if res == "quit":
            bye()
            return


if __name__ == "__main__":
    run()
