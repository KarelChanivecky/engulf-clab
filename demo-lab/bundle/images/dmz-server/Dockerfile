FROM eclab-demo/router-base:0.1

RUN mkdir -p /srv/www && printf '%s\n' 'eclab Dockerfile-built DMZ server' > /srv/www/index.html
CMD ["httpd", "-f", "-p", "8080", "-h", "/srv/www"]
