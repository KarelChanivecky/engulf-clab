FROM alpine:3.22

RUN apk add --no-cache busybox-extras && \
    mkdir -p /srv/www && \
    printf '%s\n' 'eclab archive-backed DMZ server' > /srv/www/index.html
CMD ["httpd", "-f", "-p", "8080", "-h", "/srv/www"]
