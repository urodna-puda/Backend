FROM nginx:1.17.4-alpine

RUN rm /etc/nginx/conf.d/default.conf &&\
    mkdir /var/www/static
COPY nginx.conf /etc/nginx/conf.d
