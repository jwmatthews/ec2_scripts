#!/bin/sh

# Assumes that "install_rpm_setup.sh" has already been run
source ./functions.sh

# Install EPEL
rpm -Uvh http://download.fedoraproject.org/pub/epel/6/i386/epel-release-6-8.noarch.rpm || {
    echo "Unable to install EPEL"
    exit 1;
}

# Set hostname of instance to EC2 public hostname
HOSTNAME=`curl -s http://169.254.169.254/latest/meta-data/public-hostname`
hostname ${HOSTNAME}
sed -i "s/^HOSTNAME.*/HOSTNAME=${HOSTNAME}/" /etc/sysconfig/network


cd /etc/yum.repos.d && wget http://repos.fedorapeople.org/repos/pulp/pulp/rhel-pulp.repo || {
    echo "Unable to download Pulp repo file"
    exit 1;
}

# Install mongo first so it has more time to initialize
yum install -y mongodb-server mongodb pymongo || {
    echo "yum install of mongo failed"
    exit 1;
}
chkconfig mongod on
service mongod start

# Workaround to avoid:  
# Error unpacking rpm package m2crypto-0.21.1.pulp-8.el6.x86_64
# error: unpacking of archive failed on file /usr/lib64/python2.6/site-packages/M2Crypto/DSA.pyc: cpio: lsetfilecon
yum --disablerepo="pulp-v2-stable" --enablerepo="pulp-v2-testing" update -y m2crypto || {
    echo "yum update of m2crypto failed"
    exit 1;
}


#yum --disablerepo="pulp-v2-stable" --enablerepo="pulp-v2-beta" groupinstall -y pulp-server pulp-admin || {
yum --disablerepo="pulp-v2-stable" --enablerepo="pulp-v2-testing" groupinstall -y pulp-server pulp-admin || {
    echo "yum groupinstall of pulp-server pulp-admin failed"
    exit 1;
}
sed -i "s/^url: tcp://localhost:5672.*/url: tcp://${HOSTNAME}:5672/" /etc/pulp/server.conf
sed -i "s/^host = localhost.localdomain/host = ${HOSTNAME}/" /etc/pulp/admin/admin.conf

chkconfig qpidd on
service qpidd start

echo "RPMs installed, waiting for mongo: `date`"
CMD="grep 'waiting for connections on port 27017' /var/log/mongodb/mongodb.log"
waitfor "${CMD}" "Waiting for mongodb to finish initialization" 10 30
echo "Completed check that mongo is available: `date`"

pulp-manage-db || {
    echo "Failure with pulp-manage-db"
    exit 1;
}

chkconfig httpd on
service httpd start

#
# Cloning git repo so the curl scripts under playpen are available to setup our HTTPS cert
#
yum install -y git
cd ~
git clone https://github.com/pulp/pulp.git

cd pulp/playpen/certs && ./setup.sh || {
    echo "Failed to setup https cert"
    exit 1;
}
