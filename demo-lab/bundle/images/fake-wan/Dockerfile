FROM eclab-demo/router-base:0.1

COPY entrypoint.sh /usr/local/bin/eclab-fake-wan
RUN chmod 0755 /usr/local/bin/eclab-fake-wan
ENTRYPOINT ["/usr/local/bin/eclab-fake-wan"]
