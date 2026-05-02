import json, os
from http.server import HTTPServer, BaseHTTPRequestHandler

STATE_FILE="/root/listingsniper/state.json"

HTML=open('/root/listingsniper/dashboard.html').read()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args): pass
    def send_json(self,data):
        body=json.dumps(data).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",len(body)); self.end_headers(); self.wfile.write(body)
    def send_html(self,html):
        body=html.encode()
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",len(body)); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=self.path.split("?")[0]
        if path=="/" or path=="/dashboard": self.send_html(HTML)
        elif path=="/state":
            try:
                with open(STATE_FILE) as f: data=json.load(f)
            except: data={"running":False,"error":"State file not found"}
            self.send_json(data)
        elif path=="/ctrl":
            from urllib.parse import parse_qs, urlparse
            cmd = parse_qs(urlparse(self.path).query).get("cmd",[""])[0]
            try:
                with open(STATE_FILE) as f: data=json.load(f)
                if cmd=="start": data["running"]=True
                elif cmd=="stop": data["running"]=False
                with open(STATE_FILE,"w") as f: json.dump(data,f,indent=2)
            except: pass
            self.send_json({"ok":True})
        else: self.send_response(404); self.end_headers()

if __name__=="__main__":
    print("ListingSniper Dashboard → http://0.0.0.0:8081")
    HTTPServer(("0.0.0.0",8081),Handler).serve_forever()
