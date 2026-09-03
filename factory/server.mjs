import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createProjectRegistry } from "./lib/config.mjs";
import { createLauncher } from "./lib/launch.mjs";
import { createRunStore } from "./lib/runs.mjs";

const publicDir = fileURLToPath(new URL("./public/", import.meta.url));
const assets = new Map([
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/app.js", ["app.js", "text/javascript; charset=utf-8"]],
  ["/ui.js", ["ui.js", "text/javascript; charset=utf-8"]],
  ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
]);

function sendJson(response, value, status = 200) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

async function readLaunch(request) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 65_536) throw new Error("request too large");
  }
  const value = JSON.parse(body);
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some((key) => !["projectId", "provider", "prompt"].includes(key))) throw new Error("invalid launch request");
  return value;
}

export function createFactoryServer({ keepaliveMs = 15_000, store = createRunStore(), launcher = createLauncher({ store, projects: createProjectRegistry() }) } = {}) {
  return createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    if (request.method === "POST" && url.pathname === "/api/runs") {
      try {
        const { projectId, provider, prompt } = await readLaunch(request);
        const result = launcher.launch({ projectId, provider, prompt });
        sendJson(response, result, 201);
      } catch (error) {
        sendJson(response, { error: error instanceof Error ? error.message : "invalid launch request" }, 400);
      }
      return;
    }
    if (request.method !== "GET") {
      response.writeHead(405).end();
      return;
    }
    if (url.pathname === "/api/snapshot") {
      if (url.searchParams.has("run")) {
        try {
          store.select(url.searchParams.get("run") || null);
        } catch {
          response.writeHead(404).end();
          return;
        }
      }
      sendJson(response, store.snapshot());
      return;
    }
    if (url.pathname === "/api/events") {
      response.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
      });
      response.write(": keepalive\n\n");
      const timer = setInterval(() => response.write(": keepalive\n\n"), keepaliveMs);
      const unsubscribe = store.subscribe((event) => response.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`));
      request.on("close", () => {
        clearInterval(timer);
        unsubscribe();
      });
      return;
    }
    const asset = assets.get(url.pathname);
    if (!asset) {
      response.writeHead(404).end();
      return;
    }
    try {
      const [name, contentType] = asset;
      response.writeHead(200, { "content-type": contentType, "cache-control": "no-store" });
      response.end(await readFile(`${publicDir}/${name}`));
    } catch {
      response.writeHead(500).end("Factory asset unavailable");
    }
  });
}

export async function startFactoryServer(options = {}) {
  const server = createFactoryServer(options);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(options.port ?? 0, "127.0.0.1", resolve);
  });
  return server;
}

if (import.meta.main) {
  const server = await startFactoryServer({ port: Number(process.env.PORT ?? 4317) });
  const address = server.address();
  console.log(`Coderails Factory listening at http://127.0.0.1:${address.port}`);
}
