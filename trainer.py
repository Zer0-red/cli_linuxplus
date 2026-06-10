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
         "e": "umount detaches; fails