import express, { type Express } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import { createProxyMiddleware } from "http-proxy-middleware";
import { logger } from "./lib/logger";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());

// ── Reverse proxy ────────────────────────────────────────────────────────────
// Forward every request to the Flask server (ANYDOWN backend) on port 8000.
// Flask serves:
//   GET /              → ANYDOWN frontend HTML
//   GET /api/info      → yt-dlp video info (JSON)
//   GET /api/download  → file download stream
//
// Using a proxy keeps Flask as the single source of truth; this Node process
// is only needed so Replit's application router can expose the app at "/".
app.use(
  "/",
  createProxyMiddleware({
    target: "http://localhost:8000",
    changeOrigin: true,
    on: {
      error: (_err, _req, res: any) => {
        if (!res.headersSent) {
          res
            .status(502)
            .set("Content-Type", "application/json")
            .end(
              JSON.stringify({
                error:
                  "Flask server is starting up — wait a moment and refresh.",
              }),
            );
        }
      },
    },
  }),
);

export default app;
