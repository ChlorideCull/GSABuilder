#!/usr/bin/env python3
import os.path
import subprocess
import math
import tempfile
import argparse
import shutil
import json
import ipaddress
import time
from proto import network_configurator_pb2 as pb

parser = argparse.ArgumentParser(description="GSA Builder",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="I *want* the software\nThey kept maintaining it up until 2014, version 7.XXX\nWe're on version 5.1 I think?\n\t- Cursed Silicon, 2025")
parser.add_argument("--local-bundle", help="Path to the local unpacked install bundle.", default="install_bundle")
parser.add_argument("device", help="Device to partition and install on.")
parser.add_argument("--generalize", help="Make a 'generic' install that works on unofficial hardware, and VMs.", action="store_true")
parser.add_argument("--eth1-mac", help="MAC address of eth1, for example 00:15:5D:56:C3:0A. Default pulled from hardware.")
args = parser.parse_args()

rootpath = os.path.abspath(args.local_bundle)
target = args.device

tempdir = tempfile.mkdtemp(prefix="gsa")

def DownloadAndUnpackBundle(bundledir):
    os.makedirs(bundledir, exist_ok=True)
    if (os.path.exists(os.path.join(bundledir, "manifest"))):
        print("Found already downloaded bundle")
        return
    dlproc = subprocess.run(["sh", "-c", "curl -f -s 'https://dl.google.com/dl/enterprise/install_bundle-10000967-7.6.512-18.bin' | pv -p -e -r -a -s 6335286742 --buffer-size 32M -N 'Download' -c | gpg --yes --quiet --decrypt | gpg --yes --quiet --decrypt --pinentry-mode loopback --passphrase 'Kx9zw3SN0dQuwalil53U05cBnjq7IrzW8vkWgVAz2aFrEriTg0j13yueq9Dt54xV' | pv -p -e -r -a -s 6746659172 -N 'Decryption' -c | tar xz"], cwd=bundledir)
    if dlproc.returncode != 0:
        # Probably a 404. Try again with the archived URL.
        subprocess.run(["sh", "-c", "curl -f -s 'https://web.archive.org/web/20230806225106if_/https://dl.google.com/dl/enterprise/install_bundle-10000967-7.6.512-18.bin' | pv -p -e -r -a -s 6335286742 --buffer-size 32M -N 'Download' -c | gpg --yes --quiet --decrypt | gpg --yes --quiet --decrypt --pinentry-mode loopback --passphrase 'Kx9zw3SN0dQuwalil53U05cBnjq7IrzW8vkWgVAz2aFrEriTg0j13yueq9Dt54xV' | pv -p -e -r -a -s 6746659172 -N 'Decryption' -c | tar xz"], check=True, cwd=bundledir)

def PartitionAndFormat():
    targetblocksize = int(open("/sys/block/" + target + "/queue/logical_block_size").read())
    targetblockcount = int(open("/sys/block/" + target + "/size").read())
    targetlogicalperphysical = int(open("/sys/block/" + target + "/queue/physical_block_size").read()) / targetblocksize
    targetblockspermb = int((1024*1024)/targetblocksize)

    bootpartsizeblocks = (1 * 1024 * 1024 * 1024) / targetblocksize

    # format device as MBR
    # new partition, primary, ext3, 1 GB
    # new partition, logical, LVM, rest of disk
    # make a volume group "GSA" on second partition
    # create a logical volume "System", 17 GB, format ext4
    # create a logical volume "Data", rest of VG -256 MB, format ext4
    # make a folder in /tmp to act as the target root path
    # mount System LV as /
    # mount Data LV as /data
    # mount first partition as /boot
    bootend = bootpartsizeblocks+targetblockspermb
    datastart = int(math.ceil((bootend+targetlogicalperphysical)/targetblockspermb)*targetblockspermb) # Closest 1MB boundary.
    print("Creating MBR on {0}".format(target))
    subprocess.run(["vgchange", "-an", "GSA"])
    subprocess.run(["blkdiscard", "-f", "/dev/{0}".format(target)])
    subprocess.run(["parted", "-s", "/dev/"+target, "mktable", "msdos"], check=True)
    print("Erasing LVM signature")
    subprocess.run(["dd", "bs={0}".format(targetblocksize), "if=/dev/zero", "of=/dev/{0}".format(target), "seek={0}".format(datastart), "count={0}".format(int(targetblockspermb*4))])
    print("Creating partitions on {0}".format(target))
    subprocess.run(["parted", "-s", "/dev/"+target, "mkpart", "primary", "ext3", "{0}s".format(targetblockspermb), "{0}s".format(bootpartsizeblocks+2048)], check=True)
    subprocess.run(["parted", "-s", "/dev/"+target, "mkpart", "primary", "{0}s".format(datastart), "{0}s".format(targetblockcount-1)], check=True)
    subprocess.run(["parted", "-s", "/dev/"+target, "type", "2", "0x8e"], check=True)
    print("Creating LVM PV and 'GSA' VG on {0}2".format(target))
    subprocess.run(["pvcreate", "-ff", "-y", "/dev/{0}2".format(target)], check=True)
    subprocess.run(["vgcreate", "GSA", "/dev/{0}2".format(target)], check=True)
    print("Creating LVs on 'GSA' VG")
    subprocess.run(["lvcreate", "-y", "-L", "17G", "GSA", "-n", "System"], check=True)
    subprocess.run(["lvcreate", "-y", "-l", "100%FREE", "GSA", "-n", "Data"], check=True)
    subprocess.run(["lvreduce", "-y", "-L", "-256M", "GSA/Data"], check=True) # for e2scrub
    print("Formatting boot on /dev/{0}1 as ext3".format(target))
    subprocess.run(["mkfs.ext3", "-F", "-L", "GSABoot", "/dev/{0}1".format(target)], check=True)
    print("Formatting system LV on /dev/GSA/System as ext4")
    subprocess.run(["mkfs.ext4", "-F", "-L", "GSASystem", "/dev/GSA/System"], check=True)
    print("Formatting data LV on /dev/GSA/Data as ext4")
    subprocess.run(["mkfs.ext4", "-F", "-L", "GSAData", "/dev/GSA/Data"], check=True)

def Mount(tempdir):
    print("Mounting partitions")
    subprocess.run(["mount", "/dev/GSA/System", tempdir], check=True)
    os.makedirs(os.path.join(tempdir, "boot"))
    subprocess.run(["mount", "/dev/{0}1".format(target), os.path.join(tempdir, "boot")], check=True)
    os.makedirs(os.path.join(tempdir, "data"))
    subprocess.run(["mount", "/dev/GSA/Data", os.path.join(tempdir, "data")], check=True)
    print("Mounting virtual filesystems")
    os.makedirs(os.path.join(tempdir, "proc"))
    os.makedirs(os.path.join(tempdir, "sys"))
    os.makedirs(os.path.join(tempdir, "dev"))
    os.makedirs(os.path.join(tempdir, "dev/pts"))
    os.makedirs(os.path.join(tempdir, "dev/shm"))
    os.makedirs(os.path.join(tempdir, "run"))
    subprocess.run(["mount", "proc", os.path.join(tempdir, "proc"), "-t", "proc", "-o", "nosuid,noexec,nodev"], check=True)
    subprocess.run(["mount", "sys", os.path.join(tempdir, "sys"), "-t", "sysfs", "-o", "nosuid,noexec,nodev,ro"], check=True)
    subprocess.run(["mount", "udev", os.path.join(tempdir, "dev"), "-t", "devtmpfs", "-o", "mode=0755,nosuid"], check=True)
    subprocess.run(["mount", "devpts", os.path.join(tempdir, "dev/pts"), "-t", "devpts", "-o", "mode=0620,gid=5,nosuid,noexec"], check=True)
    subprocess.run(["mount", "shm", os.path.join(tempdir, "dev/shm"), "-t", "tmpfs", "-o", "mode=1777,nosuid,nodev"], check=True)
    subprocess.run(["mount", "run", os.path.join(tempdir, "run"), "-t", "tmpfs", "-o", "mode=1777,strictatime,nosuid,nodev"], check=True)

def GenerateFstab(tempdir):
    print("Generating fstab")
    findmnt = subprocess.run(["findmnt", "-Rrnc", "-o", "UUID,TARGET,FSTYPE,OPTIONS", tempdir], capture_output=True, text=True)
    with open(os.path.join(tempdir, "etc/fstab"), mode="wt") as f:
        for line in findmnt.stdout.split("\n"):
            if len(line) == 0:
                continue
            if line[0] == " ":
                continue
            splitline = line.split(" ")
            uuid = splitline[0]
            mountpoint = splitline[1][len(tempdir):]
            if mountpoint == "":
                mountpoint = "/"
            fstype = splitline[2]
            options = splitline[3]
            f.write("UUID={0}\t{1}\t{2}\t{3}\t0 1\n".format(uuid, mountpoint, fstype, options))

def GenerateNetworkConfig(tempdir, eth1mac):
    print("Generating network config")
    eth0info = subprocess.run(["ip", "-j", "addr", "show", "dev", "eth0"], capture_output=True, encoding='utf8', check=True)
    eth0info = json.loads(eth0info.stdout)[0]
    eth0mac = eth0info["address"].upper()
    eth0ipv4 = [x for x in eth0info["addr_info"] if x["family"] == "inet"][0]
    eth0ipv4addr = eth0ipv4["local"]
    eth0ipv4net = ipaddress.IPv4Network("{0}/{1}".format(eth0ipv4addr, eth0ipv4["prefixlen"]), strict=False)
    eth0ipv4mask = str(eth0ipv4net.netmask)

    routeinfo = subprocess.run(["ip", "-j", "route"], capture_output=True, encoding='utf8', check=True)
    routeinfo = json.loads(routeinfo.stdout)
    eth0ipv4gateway = [x["gateway"] for x in routeinfo if x["dev"] == "eth0" and x["dst"] == "default"][0]

    with open(os.path.join(tempdir, "etc/sysconfig/network-scripts/ifcfg-eth0"), mode="wt") as f:
        f.writelines([
            "DEVICE=eth0\n",
            "HWADDR={0}\n".format(eth0mac),
            "ONBOOT=yes\n",
            "BOOTPROTO=none\n",
            "MTU=1500\n",
            "IPADDR={0}\n".format(eth0ipv4addr),
            "NETMASK={0}\n".format(eth0ipv4mask)
        ])
    
    with open(os.path.join(tempdir, "etc/sysconfig/network-scripts/route-eth0"), mode="wt") as f:
        f.write("default via {0} dev eth0\n".format(eth0ipv4gateway))

    if not eth1mac:
        eth1info = subprocess.run(["ip", "-j", "addr", "show", "dev", "eth1"], capture_output=True, encoding='utf8', check=True)
        eth1info = json.loads(eth1info.stdout)[0]
        eth1mac = eth1info["address"].upper()

    with open(os.path.join(tempdir, "etc/sysconfig/network-scripts/ifcfg-eth1"), mode="wt") as f:
        f.writelines([
            "DEVICE=eth1\n",
            "HWADDR={0}\n".format(eth1mac),
            "ONBOOT=yes\n",
            "BOOTPROTO=none\n",
            "MTU=1500\n",
            "IPADDR=192.168.255.1\n",
            "NETMASK=255.255.255.0\n"
        ])

    with open(os.path.join(tempdir, "etc/sysconfig/network"), mode="wt") as f:
        f.writelines([
            "NETWORKING=yes\n",
            "NETWORKING_IPV6=yes\n",
            "IPV6_AUTOCONF=no\n",
            "IPV6FORWARDING=no\n",
            "HOSTNAME=ent1\n"
        ])
    
    with open(os.path.join(tempdir, "etc/hostname"), mode="wt") as f:
        f.write("ent1\n")
    
    with open(os.path.join(tempdir, "etc/resolv.conf"), mode="wt") as f:
        f.write("\n\n")
    
    pb_nic = pb.NetworkConfiguration() # pyright: ignore[reportAttributeAccessIssue]
    iptables = pb.IptablesConfiguration() # pyright: ignore[reportAttributeAccessIssue]
    routes = pb.StaticRoutesConfiguration() # pyright: ignore[reportAttributeAccessIssue]
    time = pb.TimeConfiguration() # pyright: ignore[reportAttributeAccessIssue]
    time.timezone = 'America/Los_Angeles'
    iptables.adminhttp = True
    iptables.feedergatehttp = True
    iptables.sshd_enabled = True
    iptables.adminnic_device = "eth0"
    pb_nic.primary.device = "eth0"
    pb_nic.primary.ipv4_address = eth0ipv4addr
    pb_nic.primary.ipv4_netmask = eth0ipv4mask
    pb_nic.primary.ipv4_gateway = eth0ipv4gateway
    pb_nic.primary.enabled = True
    pb_nic.primary.mac_address = eth0mac
    default_route = routes.routes.add()
    default_route.gateway = pb_nic.primary.ipv4_gateway
    default_route.is_default = True
    default_route.device = "eth0"


    with open(os.path.join(tempdir, "export/hda3/platform/conf/iptables.pb"), mode="wb") as f:
        f.write(iptables.SerializeToString())
    with open(os.path.join(tempdir, "export/hda3/platform/conf/network.pb"), mode="wb") as f:
        f.write(pb_nic.SerializeToString())
    with open(os.path.join(tempdir, "export/hda3/platform/conf/static_routes.pb"), mode="wb") as f:
        f.write(routes.SerializeToString())
    with open(os.path.join(tempdir, "export/hda3/platform/conf/time.pb"), mode="wb") as f:
        f.write(time.SerializeToString())
    
    with open(os.path.join(tempdir, "etc/sysconfig/network_configurator_force"), mode="wt") as f:
        f.write("NOOP")

def MakeDirectoryTree(tempdir, version, release):
    print("Setting up GSA-specific directory tree")
    # see PrePackageInstallSetupImage in common_install_steps.py
    for directory in ('/boot/grub', '/root/.gnupg', '/var/tmp', '/var/lib/rpm', '/etc/sysconfig/network-scripts', '/data/{0}'.format(version)):
        if not os.path.exists(os.path.join(tempdir, directory)):
            os.makedirs(os.path.join(tempdir, directory))
    
    original_umask = os.umask(0)

    for directory, permissions in [
        ('data/{0}/tmp', 0o1777),
        ('data/{0}/logs', 0o1777),
        ('data/{0}/conf', 0o1777),
        ('data/{0}/spelling', 0o1777),
        ('data/{0}/connectormgr-prod', 0o1777),
        ('data/{0}/connectormgr-test', 0o1777),
        ('data/{0}/lang_packs', 0o1777),
        ('export/hda3/{0}', 0o1777),
        ('export/hda3/{0}/local/google/bin', 0o755),
        ('data/{0}/binaries/{1}/local/google/bin', 0o755)
        ]:
            if not os.path.exists(os.path.join(tempdir, directory.format(version, release))):
                os.makedirs(os.path.join(tempdir, directory.format(version, release)), permissions)

    os.umask(original_umask)

    os.symlink('../../../data/{0}'.format(version),
             os.path.join(tempdir, 'export/hda3/{0}/data'.format(version)))
    os.symlink('../../data/{0}/tmp'.format(version),
                os.path.join(tempdir, 'export/hda3/tmp'.format(version)))
    os.symlink('../../data/{0}/tmp'.format(version),
                os.path.join(tempdir, 'export/hda3/logs'.format(version)))
    os.symlink('../../../data/{0}/tmp'.format(version),
                os.path.join(tempdir, 'export/hda3/{0}/logs'.format(version)))
    os.symlink('../../data/{0}/lang_packs'.format(version),
                os.path.join(tempdir, 'export/hda3/lang_packs'.format(version)))
    os.symlink('../../../data/{0}/spelling'.format(version),
                os.path.join(tempdir, 'export/hda3/{0}/spelling'.format(version)))
    os.symlink(
        '../../../../../../data/{0}/connectormgr-prod'.format(version),
        os.path.join(tempdir, 'export/hda3/{0}/local/google/bin/connectormgr-prod'.format(version)))
    os.symlink(
        '../../../../../../data/{0}/connectormgr-test'.format(version),
        os.path.join(tempdir, 'export/hda3/{0}/local/google/bin/connectormgr-test'.format(version)))

if not args.generalize:
    print("/!\\ Building an image that will only work on official hardware!")

print("/!\\ GOING TO OBLITERATE /DEV/{0} /!\\".format(target.upper()))
print("This script will irrevocably remove everything on /dev/{0}. Are you sure it's the right device?".format(target))
subprocess.run(["lsblk", "/dev/{0}".format(target)])
print("Continuing in 10 seconds...")
time.sleep(10)

DownloadAndUnpackBundle(rootpath)
PartitionAndFormat()

print("Executing manifest (thanks Google)")
NUEVO_VERSION = ""
GSA_SW_VERSION = ""
MBID = ""
PACKAGE_LIST = []
exec(open(os.path.join(rootpath, "manifest")).read())
GSA_SW_VERSION_REAL = GSA_SW_VERSION.split("-")[0]
GSA_RELEASE = GSA_SW_VERSION.split("-")[1]

Mount(tempdir)
MakeDirectoryTree(tempdir, GSA_SW_VERSION_REAL, GSA_RELEASE)

print("Installing all packages (this will take a while, go get a coffee)")
rpmlist = [os.path.join(rootpath, x["rpm"]) for x in PACKAGE_LIST]
subprocess.run(["rpm", "-r", tempdir, "--ignorearch", "--noverify", "--nofiledigest", "--nosignature", "--nodeps", "--replacefiles", "--force", "-i"] + rpmlist, check=True)

GenerateFstab(tempdir)

if args.generalize:
    print("Downloading kernel from Rocky Linux 8")
    kernelcore = os.path.join(tempdir, "run", "kernel-core.rpm")
    kernelmods = os.path.join(tempdir, "run", "kernel-modules.rpm")
    kernelmods2 = os.path.join(tempdir, "run", "kernel-modules-extra.rpm")
    subprocess.run(["curl", "-o", kernelcore, "https://download.rockylinux.org/pub/rocky/8/BaseOS/x86_64/os/Packages/k/kernel-core-4.18.0-553.63.1.el8_10.x86_64.rpm"], check=True)
    subprocess.run(["curl", "-o", kernelmods, "https://download.rockylinux.org/pub/rocky/8/BaseOS/x86_64/os/Packages/k/kernel-modules-4.18.0-553.63.1.el8_10.x86_64.rpm"], check=True)
    subprocess.run(["curl", "-o", kernelmods2, "https://download.rockylinux.org/pub/rocky/8/BaseOS/x86_64/os/Packages/k/kernel-modules-extra-4.18.0-553.63.1.el8_10.x86_64.rpm"], check=True)
    print("Installing kernel from Rocky Linux 8")
    subprocess.run(["rpm", "-r", tempdir, "--ignorearch", "--noverify", "--nofiledigest", "--nosignature", "--nodeps", "--replacefiles", "--force", "-i", kernelcore, kernelmods, kernelmods2], check=True)
    kernel = "4.18.0-553.63.1.el8_10.x86_64"
    shutil.copy(os.path.join(tempdir, "lib", "modules", kernel, "vmlinuz"), os.path.join(tempdir, "boot", "vmlinuz-{0}".format(kernel)))
    shutil.copy(os.path.join(tempdir, "lib", "modules", kernel, "System.map"), os.path.join(tempdir, "boot", "System.map-{0}".format(kernel)))
else:
    kernels = [x[8:] for x in os.listdir(os.path.join(tempdir, "boot")) if x.startswith("vmlinux-")]
    kernel = kernels[0]

print("Generating initramfs and grub config")
subprocess.run(["chroot", tempdir, "/bin/mkinitrd", "-v", "/boot/initramfs-{0}.img".format(kernel), kernel], check=True)
# There are so many issues with the annoying custom grub config generator, I'll just make it myself
with open(os.path.join(tempdir, "boot/grub/grub.conf"), mode="wt") as f:
    f.writelines([
        "default 0\n",
        "timeout 10\n",
        "\n",
        "title {0} {1}\n".format(GSA_SW_VERSION, MBID),
        "\troot (hd0,0)\n",
        "\tkernel /vmlinuz-{0} root=/dev/GSA/System\n".format(kernel),
        "\tinitrd /initramfs-{0}.img\n".format(kernel)
    ])
print("Installing GRUB")
subprocess.run(["chroot", tempdir, "/usr/sbin/grub-install", "/dev/{0}".format(target)], check=True)
print("Generating GSA specific keys and config")
# Reference: common_install_steps.py in upgrade PAR
with open(os.path.join(tempdir, "etc/sysconfig/enterprise_config"), mode="wt") as f:
    f.writelines([
        "ENT_ALL_MACHINES='ent1'\n",
        "MACHINES='ent1'\n",
        "ENT_CONFIG_TYPE='super'\n",
        "DOC_PROCESSING_THREADS=8\n" # HACK: This doesn't belong here, but I can't find what is supposed to set it.
    ])
with open(os.path.join(tempdir, "etc/google/hw_manifest.py"), mode="wt") as f:
    f.writelines([
        "RAID_SPECS = { }\n",
        "DISK_CONFIG = []\n",
        "BIOS_TYPE = 'dell'\n",
        "TPM_ENABLED = False\n",
        "CPU_SPECS = { 'cores': ['4', '4'], 'speed': ['2400', '2400'], 'threads': ['8', '8'] }\n",
        "NIC_MAPPING = { 'eth0': {'system-device': 'eth0', 'config': 'managed-primary'}, 'eth1': {'system-device': 'eth1', 'config': 'webconfig'} }\n",
        "MD_CONFIG = []\n"
    ])
googleconfigpath = "/export/hda3/{0}/local/conf/google_config".format(GSA_SW_VERSION_REAL)
subprocess.run(["chroot", tempdir, "/opt/ent/customize/gsa_keygen.par", "--developer", "--install"], check=True)
subprocess.run(["chroot", tempdir, "/opt/ent/customize/gsa_config.par", "--config", "shipping", "--platform", "dell_r710_v2", "--product", "super", "--force", "--outfile", googleconfigpath], check=True)
subprocess.run(["chroot", tempdir, "/opt/ent/customize/gsa_license.par", "--config", "shipping", "--platform", "dell_r710_v2", "--product", "super", "--force", "--set", "ENT_LICENSE_ORIGINAL_START_DATE=1754389348000L", "--set", "ENT_LICENSE_ORIGINAL_END_DATE=3133700400000L", "--set", "ENT_LICENSE_ID=Dusty was here :3", "--infile", googleconfigpath, "--outfile", googleconfigpath], check=True)
subprocess.run(["chroot", tempdir, "ln", "-sf", "/usr/share/zoneinfo/US/Pacific", "/etc/localtime"], check=True)
subprocess.run(["chroot", tempdir, "chsh", "-s", "/bin/bash", "nobody"], check=True)
subprocess.run(["chroot", tempdir, "chown", "nobody", "/export/hda3/tmp"], check=True)
unameline = [x['uname_output'] for x in PACKAGE_LIST if 'uname_output' in x][0]
with open(os.path.join(tempdir, "etc/sysconfig/uname"), mode="wt") as f:
    f.write(unameline)

# At this point I could recreate the ID generation, or...
ENT_CONFIG_NAME = ""
with open(os.path.join(tempdir, "export/hda3/{0}/local/conf/google_config_local").format(GSA_SW_VERSION_REAL)) as f:
    exec([x for x in f.read().split("\n") if x.startswith("ENT_CONFIG_NAME =")][0])

with open(os.path.join(tempdir, "etc/postinstall_motd"), mode="wt") as motd:
    with open(os.path.join(tempdir, "etc/postinstall_motd"), mode="wt") as issue:
        lines = [
            "\nVERSION: {0}\n".format(GSA_SW_VERSION),
            "\nBUILD ID: {0}\n".format(MBID),
            "\nGSN: {0}\n".format(ENT_CONFIG_NAME)
        ]
        motd.writelines(lines)
        issue.writelines(lines)

#GSN_PREFIX_MAP = {
#    (ONEWAY, DELL_2950): 'S5',
#    (ONEWAY, DELL_2950_V2): 'S5',
#    (SUPER, DELL_2950_BIG): 'T1',
#    (SUPER, DELL_2950_BIG_V2): 'T1',
#    (SUPER, DELL_R710): 'T2',
#    (SUPER, DELL_R710_V2): 'T3',
#    (SUPER, DELL_R720XD): 'T4',
#    (SUPER, DELL_R730XD): 'T5',
#    (UBER, DELL_R710_BIG): 'U1',
#    (UBER, DELL_R710_BIG_V2): 'U2',
#    (UBER, DELL_R720XD_BIG): 'U3',
#    (UBER, DELL_R720XD_BIG_V2): 'U3',
#    (UBER, DELL_R730XD_BIG): 'U4',
#    (SNAPPER, DELL_R310): 'I2',
#    (SNAPPER, DELL_R420): 'I3',
#    (SNAPPER, DELL_2900): 'I1',
#    (SNAPPER, DELL_1950): 'I1',
#    (SNAPPER, DELL_1950_V2): 'I1'
#}
with open(os.path.join(tempdir, "etc/google/sw_version"), mode="wt") as f:
    f.write(GSA_SW_VERSION)
with open(os.path.join(tempdir, "etc/google/nuevo_version"), mode="wt") as f:
    f.write(NUEVO_VERSION)
with open(os.path.join(tempdir, "etc/google/master_build_id"), mode="wt") as f:
    f.write("T3.{0}".format(MBID))
with open(os.path.join(tempdir, "etc/google/enterprise_sysinfo"), mode="wt") as f:
    f.writelines([
        "GSN = '{0}'\n".format(ENT_CONFIG_NAME),
        "PLATFORM = 'dell_r710_v2'\n",
        "HW_PLATFORM = 'dell_r710_v2'\n",
        "PRODUCT = 'super'\n"
    ])

GenerateNetworkConfig(tempdir, args.eth1_mac)

print("Unmounting")
subprocess.run(["umount", "-R", tempdir])
os.rmdir(tempdir)
print("Done!")
print("Please note that it may take up to 20 minutes for the system to be ready after first boot.")
print("Once done, you can connect a device to eth1, and connect to http://192.168.255.1:1111 to start the Network and System Settings wizard.")

# /bin/mkinitrd /boot/initramfs-3.14.44_gsa-x64_1.9.img 3.14.44_gsa-x64_1.9
# /usr/sbin/grub_cfg.par -c new --kernels vmlinux-3.14.44_gsa-x64_1.9 --appends initrd=/boot/initramfs-3.14.44_gsa-x64_1.9.img --gsa_sw_ver GSA_SW_VERSION --mbid MBID -o /boot/grub/grub.cfg
# /usr/sbin/grub-install target
# /opt/ent/customize/gsa_keygen.par -r -i -P dell_r710_v2 --product super
# # TODO: Secure key generation is broken af, use devel_release keys for now, which sets passwords to "test" and lets a bunch of google people SSH into your machine
# # /opt/ent/customize/gsa_keygen.par -s -a keybundle.bin -P dell_r710_v2 --product super
# /opt/ent/customize/gsa_config.par --config shipping --platform dell_r710_v2 --product super -o "/export/hda3/" + GSA_SW_VERSION_REAL + "/local/conf/google_config"
# # TODO: Stub out the "DO NOT SHIP" taint? see gsa_firstboot
