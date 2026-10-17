# ROCKNIX (H700) : système de fichiers de l'image officielle, lancé comme un serveur SSH (voir systems-lab/README.md).
FROM agm-lab/rocknix-base:20261001
COPY common/make_rom.py common/fake_es.py /lab/
COPY rocknix/entrypoint.sh /lab/entrypoint.sh
ENV HOME=/storage
EXPOSE 22
CMD ["/bin/sh", "/lab/entrypoint.sh"]
