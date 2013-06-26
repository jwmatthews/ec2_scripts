#!/usr/bin/env python
import os
import sys
import time
from launch_instance import launch_instance, get_opt_parser, ssh_command, scp_to_command, run_command

if __name__ == "__main__":
    start = time.time()

    parser = get_opt_parser(vol_size=100)
    (opts, args) = parser.parse_args()
    instance = launch_instance(opts)
    hostname = instance.dns_name
    ssh_key = opts.ssh_key
    ssh_user = opts.ssh_user
    #
    # open firewall
    #
    print "Updating firewall rules"
    ssh_command(hostname, ssh_user, ssh_key, "mkdir -p ~/etc/sysconfig")
    scp_to_command(hostname, ssh_user, ssh_key, "./etc/sysconfig/iptables", "~/etc/sysconfig/iptables")
    ssh_command(hostname, ssh_user, ssh_key, "sudo mv ~/etc/sysconfig/iptables /etc/sysconfig/iptables")
    ssh_command(hostname, ssh_user, ssh_key, "sudo restorecon /etc/sysconfig/iptables")
    ssh_command(hostname, ssh_user, ssh_key, "sudo chown root:root /etc/sysconfig/iptables")
    ssh_command(hostname, ssh_user, ssh_key, "sudo service iptables restart")
    #
    # Run install script
    #
    print "Running install script for Pulp"
    scp_to_command(hostname, ssh_user, ssh_key, "./scripts/functions.sh", "~")
    scp_to_command(hostname, ssh_user, ssh_key, "./scripts/install_pulp.sh", "~")
    ssh_command(hostname, ssh_user, ssh_key, "sudo chmod +x ./install_pulp.sh")
    ssh_command(hostname, ssh_user, ssh_key, "time sudo ./install_pulp.sh &> ./pulp_rpm_setup.log ")
    #
    # Update EC2 tag with version of RCS installed
    #
    print "Update EC2 tag with RPM version of 'pulp-server' installed on %s" % (hostname)
    status, out, err = ssh_command(hostname, ssh_user, ssh_key, "rpm -q --queryformat \"%{VERSION}\" pulp-server")
    pulp_ver = out
    tag = ""
    if instance.__dict__.has_key("tags"):
        all_tags = instance.__dict__["tags"]
        if all_tags.has_key("Name"):
            tag = all_tags["Name"]
    if not tag:
        import getpass
        tag = "%s" % (getpass.getuser())
    tag += " Pulp %s" % (pulp_ver)
    instance.add_tag("Name","%s" % (tag))

    end = time.time()
    print "Pulp %s install completed on: %s in %s seconds" % (pulp_ver, hostname, end-start)

