sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-10.noarch.rpm
sudo dnf install -y https://download1.rpmfusion.org/free/el/rpmfusion-free-release-10.noarch.rpm
sudo dnf install -y https://download1.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-10.noarch.rpm
sudo dnf install -y p7zip p7zip-plugins unrar ffmpeg 