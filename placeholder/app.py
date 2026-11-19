import json
import os
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        health=self.path=='/healthz'
        body=json.dumps({'status':'infrastructure-ready' if health else 'application-not-deployed','message':'Your group infrastructure is ready. Build, migrate and deploy your reviewed application.'}).encode()
        self.send_response(200 if health else 503);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
HTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
