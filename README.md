# GSA Builder
*Bringing the yellow bastards back to life.*

This script will allow building a complete Google Search Appliance based on version 7.6.512, which is the last available version before it was discontinued.

Don't run this exposed to the internet. This product doesn't have the best security track record, which is probably partially why it got discontinued.

## Requirements

1. The script must be run under Linux.
1. The script **must** be run on the physical hardware or VM that will be used to run the actual appliance. The licensing is tied to the MAC addresses, to be specific.
1. The target disk **will be completely wiped**, and must be at least 32 GB. 18 GB is used by the system, the rest is used for data.
1. The appliance requires at least 8 GB of RAM.
1. The appliance requires two network adapters.
1. The environment that runs the `build.py` script must have access to:
    - some recent-ish version of python3
    - python-protobuf 6.31.1 or later (or just rebuild `network_configurator_pb2.py` with whatever version of `protoc` you have available)
    - curl
    - pv
    - gpg
    - tar
    - blkdiscard
    - parted
    - LVM tools
    - mkfs.ext3
    - mkfs.ext4
    - findmnt
    - rpm
1. The environment that runs the `build.py` script needs to have the traditional, non-deterministic network names (`eth0`, `eth1`, and so on)

During testing, I've been booting a VM from an Arch Linux live disc, and performing the build from there.

## Differences from the real thing
On account of this being intended for appliances, and there being no official way to perform an installation from scratch, there are some differences compared to what you would find on an appliance:

1. There is a pre-activated license valid until 2069-04-20 4:20:00 PM GMT. With an appliance, you'd get a license valid for your appliance for as long as you had an active support contract, and they've all expired now.
2. **This uses an insecure configuration.** On the appliances, all credentials and keys would be randomly generated and stored on a server. This uses development credentials and keys they helpfully shipped. If you are asked for a password, it's usually `test`. **This includes hidden accounts.**
3. Appliances would come with a RAID setup from the factory, and generally have a different configuration depending on the model. This pretends to be a weird Dell R710 with no disks and no RAID, as far as the management software is concerned :)
4. When run with `--generalize` the kernel is replaced with a slightly newer one from Rocky Linux 8, as the stock kernel is hyperspecialized to the point of only supporting the PERC controllers in the Dell servers it was intended for. Yes, it doesn't even support AHCI.
5. The appliances have an A/B partitioning setup, similar to Android devices. This doesn't, because it's highly unlikely Google is going to release an update at this point.

## Known issues
- System status will always show a temperature warning, because it's trying to probe for hardware sensors that doesn't exist.
- If you have real hardware, it's highly unlikely the ID printed on the case will match, on account of the whole "always pretending to be an R710" thing.
- Inability to build premade images - see the first point under Requirements. Fixing this requires moving some steps to a systemd service, to run once at first boot before any of the GSA services start.
- The unused, non-working initramfs generated for the build host kernel is never removed.
- The inability to make a secure image is... pretty bad. In development mode, it gets configured to be extremely insecure, and even if you *think* you've got all the wide open accounts, there's a myriad of hidden ones.

## Further reading
This is generally compatible with [the official Installation guide.](https://web.archive.org/web/20130728154604/http://www.google.com/support/enterprise/static/gsa/docs/admin/70/gsa_doc_set/installation/installation.html)
