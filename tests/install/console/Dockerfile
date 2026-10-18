# Fausse console pour le test d'installation (tests/install/e2e.sh) : serveur SSH + SFTP, utilisateur root avec mot de
# passe, carte rangée comme une Anbernic (/mnt/mmc/Roms/<console>/). Les « ROMs » sont des octets aléatoires.
FROM alpine:3.20
RUN apk add --no-cache openssh openssh-sftp-server \
 && ssh-keygen -A \
 && echo 'root:romkade' | chpasswd \
 && sed -i -e 's/^#*PermitRootLogin.*/PermitRootLogin yes/' -e 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
 && mkdir -p /mnt/mmc/Roms/SFC /mnt/mmc/Roms/GBA /mnt/mmc/Roms/MD \
 && for f in "SFC/Super Mario World (USA).sfc" "SFC/Legend of Zelda, The - A Link to the Past (USA).sfc" \
             "GBA/Metroid Fusion (USA).gba" "MD/Sonic The Hedgehog (USA, Europe).md"; do \
      head -c 65536 /dev/urandom > "/mnt/mmc/Roms/$f"; done
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
