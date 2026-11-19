# Go - build one binary, then run it in a small non-root image; the app must read the port from os.Getenv("PORT")
# The final image is alpine (it has a shell), so "kit.sh migrate" works with MIGRATE_COMMAND=/app/server migrate
# (the container filesystem is owned by root: write files to /tmp or /data, which are writable, not next to the binary)
FROM golang:1.22 AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/server .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata \
 && adduser -D -H -u 10001 app \
 && mkdir -p /app /data && chown app:app /app /data
COPY --from=build --chown=app:app /out/server /app/server
ENV PORT=8080
EXPOSE 8080
USER app
ENTRYPOINT ["/app/server"]
