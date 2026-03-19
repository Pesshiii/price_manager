FROM postgres:17

COPY docker/db/init/ /docker-entrypoint-initdb.d/
RUN chmod 644 /docker-entrypoint-initdb.d/*.sh
