#!/usr/bin/env python
#
# Assumes that the following environment variables have been set
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
import os
import stat
import subprocess
import sys
import time
from optparse import OptionParser

try:
    from boto.ec2.connection import EC2Connection
    from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
except Exception, e:
    print "Caught exception: %s" % (e)
    print "Unable to import 'boto' modules."
    print "Try:  sudo yum install python-boto"
    sys.exit(1)

def tag_instance(instance, hostname, ssh_user, ssh_key, rpm_name=None, data=None):
    tag = ""
    if instance.__dict__.has_key("tags"):
        all_tags = instance.__dict__["tags"]
        if all_tags.has_key("Name"):
            tag = all_tags["Name"]
    if not tag:
        import getpass
        tag = "%s" % (getpass.getuser())
    if rpm_name:
        status, out, err = ssh_command(hostname, ssh_user, ssh_key, "rpm -q --queryformat \"%{VERSION}\" " + rpm_name)
        tag += " %s %s" % (rpm_name, out)
    if data:
        tag += " %s" % (data.strip())
    instance.add_tag("Name","%s" % (tag))
    return tag

def run_instance(conn, ami_id, key_name, instance_type, 
        sec_group, zone="us-east-1d", vol_size=None):
    """
    @param connection: python boto connection
    @param ami_id: AMI ID
    @param key_name: SSH key name
    @param instance_type: instance type, example 'm1.large'
    @param sec_group: security group
    @param zone: optional, defaults to 'us-east-1d'
    @param vol_size: optional integer, if specified will change size of root volume to this size
    
    @return boto.ec2.instance.Instance
    """
    bdm = None
    if vol_size:
        # Create block device mapping info
        dev_sda1 = BlockDeviceType()
        dev_sda1.size = int(vol_size)
        dev_sda1.delete_on_termination = True
        bdm = BlockDeviceMapping()
        bdm['/dev/sda1'] = dev_sda1

    # Run instance
    reservation = conn.run_instances(
            ami_id,
            key_name=key_name,
            instance_type=instance_type,
            placement=zone,
            instance_initiated_shutdown_behavior="stop",
            security_groups=[sec_group],
            block_device_map=bdm)
    return reservation.instances[0]

def wait_for_running(instance, wait=120):
    """
    Sleeps till instance is up
    @param instance: 
    @type instance: boto.ec2.instance.Instance
    """
    print "Waiting for instance '%s' to come up" % (instance.id)
    for i in range(0, wait):
        instance.update()
        if instance.state != "pending":
            break
        if i % 10 == 0:
            print "Waited %s seconds for instance '%s' to come up" % (i, instance.id)
        time.sleep(1)
    if instance.state == "running":
        return True
    return False

def terminate(conn, instance):
    conn.terminate_instances([instance.id])
    print "Instance %s has been terminated" % (instance.id)

def run_command(cmd, verbose=False, exit_on_error=True, retries=0, delay=10):
    """
    @param cmd: string command to run
    @return tuple (True/False, stdout, stderr) true on sucess, false on failure
    """
    handle = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out_msg, err_msg = handle.communicate(None)
    if verbose:
        print "Ran: '%s'" % (cmd)
        print "stdout:\n%s" % (out_msg)
        print "stderr:\n%s" % (err_msg)
    if handle.returncode != 0:
        if retries > 0:
            print "Will retry %s more times command: %s" % (retries, cmd)
            print "Waiting for delay: %s seconds" % (delay)
            time.sleep(delay)
            return run_command(cmd, verbose, exit_on_error, retries - 1)
        if exit_on_error:
            print "Exiting due to error from: %s" % (cmd)
            print "stdout:\n%s" % (out_msg)
            print "stderr:\n%s" % (err_msg)
            sys.exit(1)
        return False, out_msg, err_msg
    return True, out_msg, err_msg

def scp_to_command(hostname, ssh_user, ssh_key, from_path, to_path, exit_on_error=True):
    cmd ="scp -o \"StrictHostKeyChecking no\" -i %s %s %s@%s:%s" % (ssh_key, from_path, ssh_user, hostname, to_path)
    return run_command(cmd, exit_on_error=exit_on_error)

def ssh_command(hostname, ssh_user, ssh_key, command, exit_on_error=True):
    cmd = "ssh -o \"StrictHostKeyChecking no\" -t -i %s %s@%s \"%s\"" % (ssh_key, ssh_user, hostname, command)
    return run_command(cmd, exit_on_error=exit_on_error)

def wait_for_ssh(instance, ssh_user, ssh_key, wait=40):
    """
    @param instance
    @param ssh_user
    @param ssh_key
    """
    print "Waiting for instance '%s' to listen for ssh requests" % (instance.dns_name)
    for i in range(1, wait):
        print "Attempt '%s' waiting for ssh to come up on %s" % (i, instance.dns_name)
        status, out, err = ssh_command(instance.dns_name, ssh_user, ssh_key, "ls", exit_on_error=False)
        if status:
            return True
        time.sleep(15)
    return False

def resize_root_volume(instance, ssh_user, ssh_key, dev="/dev/xvde1"):
    # Note '/dev/xvde1' is the root device on the AMIs
    # we are working with, even though our device mapping 
    # specifies them as '/dev/sda1/'
    print "Resizing %s on %s" % (dev, instance.dns_name)
    status, out, err = ssh_command(instance.dns_name, ssh_user, ssh_key, "resize2fs %s" % (dev))
    return status


def get_opt_parser(parser=None, description=None, vol_size=None):
    # RHEL 6.3 default_ami = "ami-cc5af9a5"
    default_ami = "ami-f6f16b9f" # RHEL 6.4
    default_ssh_key = None
    default_key_name = "splice"
    default_instance_type = "m1.large"
    default_zone = "us-east-1d"
    default_sec_group = "devel-testing"
    default_vol_size = vol_size
    if not default_vol_size:
        default_vol_size = 25
    if os.environ.has_key("CLOUDE_GIT_REPO"):
        default_ssh_key="%s/splice/aws/ssh-keys/splice_rsa" % os.environ["CLOUDE_GIT_REPO"]
    if not parser:
        parser = OptionParser(description=description)
    parser.add_option('--ssh_user', action='store', default="ec2-user", 
            help="SSH username")
    parser.add_option('--ssh_key', action='store', default=default_ssh_key, 
            help="Path to ssh key, defaults to: %s" % (default_ssh_key))
    parser.add_option('--ami', action='store', default=default_ami, 
        help="AMI, defaults to: %s" % (default_ami))
    parser.add_option('--key_name', action='store', default=default_key_name, 
        help="Name for ssh key in EC2, defaults to: %s" % (default_key_name))
    parser.add_option('--type', action='store', default=default_instance_type, 
        help="Instance type, defaults to: %s" % (default_instance_type))
    parser.add_option('--zone', action='store', default=default_zone,
        help="Zone to launch this instance, defaults to: %s" % (default_zone))
    parser.add_option('--group', action='store', default=default_sec_group,
        help="Security Group, defaults to: %s" % (default_sec_group))
    parser.add_option('--vol_size', action='store', type="int", default=default_vol_size,
        help="Root volume size, defaults to: %s" % (default_vol_size))
    return parser


def verify_ssh_key_perms(key_path):
    if not os.path.isfile(key_path):
        raise Exception("ssh key '%s' was not found, or is not a usable file." % (key_path))
    mode = oct(os.stat(key_path)[stat.ST_MODE])[-3:]
    if mode != '600':
        raise Exception("ssh key '%s' needs to have permissions '600' yet is set to '%s'. Please fix and retry" % (key_path, mode))

def launch_instance(opts, tag=None):
    """
    @param opts: options from optparse.OptionParser.parse_args()
    @param tag: optional string to use to tag this instance for EC2 console
    """
    ami_id = opts.ami
    key_name = opts.key_name
    instance_type = opts.type
    zone = opts.zone
    group = opts.group
    vol_size = opts.vol_size
    ssh_user = opts.ssh_user
    ssh_key = opts.ssh_key

    verify_ssh_key_perms(ssh_key)
    conn = EC2Connection()
    instance = run_instance(conn, ami_id=ami_id, key_name=key_name,
            instance_type=instance_type, sec_group=group, 
            zone=zone, vol_size=vol_size)

    if not wait_for_running(instance):
        print "Instance <%s> did not enter running state" % (instance.id)
        terminate(conn, instance)
        return None
    instance.update() # Refresh instance state & dns_name now that is running
    # Add a tag so this instance is easier to distinguish in EC2 console
    if not tag:
        import getpass
        WHOAMI=getpass.getuser() # Used to label the instance in ec2 webui
        tag = "%s" % (getpass.getuser())
    instance.add_tag("Name","%s" % (tag))

    if not wait_for_ssh(instance, ssh_user=ssh_user, ssh_key=ssh_key):
        print "%s never came up for SSH access" % (instance.dns_name)
        terminate(conn, instance)
        raise Exception("Instance never came up")
    # No longer needed for RHEL 6.4+
    #if not resize_root_volume(instance, ssh_user=ssh_user, ssh_key=ssh_key):
    #    print "Failed to resize root filesystem on %s" % (instance.dns_name)
    #    terminate(conn, instance)
    #    return None
    return instance


if __name__ == "__main__":
    parser = get_opt_parser()
    (opts, args) = parser.parse_args()
    instance = launch_instance(opts)
    print "%s is up" % (instance.dns_name)

