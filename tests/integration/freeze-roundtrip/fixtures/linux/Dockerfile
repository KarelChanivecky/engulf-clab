FROM freeze-roundtrip/@RUN@-base:1
COPY marker /roundtrip-linux
COPY probe.py /roundtrip-probe.py
LABEL org.engulf.freeze-roundtrip.linux="linux-v1"
# Keep the packaged PKI entrypoint inherited through the base recipe.
CMD ["sleep", "infinity"]
