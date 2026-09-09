FROM eclab.containers.pki/fedora:latest

RUN dnf install -y iproute nginx && dnf clean all
COPY nginx.conf /etc/nginx/conf.d/eclab-demo.conf

CMD ["nginx", "-g", "daemon off;"]
