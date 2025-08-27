FROM postgres:15
COPY infra/migrations /migrations
CMD ["bash", "-lc", "echo 'Use Postgres init scripts under docker-entrypoint-initdb.d'"]
