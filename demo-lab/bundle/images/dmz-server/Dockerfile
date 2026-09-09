FROM eclab.containers.pki/debian:latest

RUN apt-get update && \
    apt-get install -y --no-install-recommends iproute2 nginx && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/conf.d/eclab-demo.conf

CMD ["nginx", "-g", "daemon off;"]
