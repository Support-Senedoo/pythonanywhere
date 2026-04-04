#!/usr/bin/env node
/**
 * Serveur MCP SSH minimal : même outil `execute_command` que ssh-mcp-server (npm),
 * mais lecture correcte de privateKey (le paquet npm passait une Promise à ssh2).
 */
import { readFile } from "node:fs/promises";
// Sous Node « exports », utiliser le sous-chemin exact (pas …/server/index.js).
import { Server } from "@modelcontextprotocol/sdk/server";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { Client } from "ssh2";

const server = new Server(
  { name: "mcp-pa-ssh", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "execute_command",
      description: "Execute command on remote server",
      inputSchema: {
        type: "object",
        properties: {
          command: { type: "string" },
          stdin: { type: "string" },
          host: { type: "string" },
          port: { type: "number", default: 22 },
          username: { type: "string" },
          privateKeyPath: { type: "string" },
        },
        required: ["command", "host", "username", "privateKeyPath"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== "execute_command") {
    throw new Error("Unknown tool");
  }

  const { command, stdin, host, port, username, privateKeyPath } =
    request.params.arguments;

  let privateKey;
  try {
    privateKey = await readFile(privateKeyPath);
  } catch (e) {
    return {
      content: [
        {
          type: "text",
          text: `Lecture clé impossible (${privateKeyPath}): ${e.message}`,
        },
      ],
      isError: true,
    };
  }

  const conn = new Client();
  const p = new Promise((resolve) => {
    conn.on("ready", () => {
      conn.exec(command, (err, stream) => {
        if (err) {
          conn.end();
          resolve({
            content: [{ type: "text", text: `exec: ${err.message}` }],
            isError: true,
          });
          return;
        }
        let out = "";
        stream.on("data", (d) => {
          out += d.toString();
        });
        stream.stderr?.on("data", (d) => {
          out += d.toString();
        });
        stream.on("close", () => {
          conn.end();
          resolve({ content: [{ type: "text", text: out || "(vide)" }] });
        });
        if (stdin) {
          stream.write(stdin);
        }
        stream.end();
      });
    });

    conn.on("error", (err) => {
      resolve({
        content: [{ type: "text", text: `SSH: ${err.message}` }],
        isError: true,
      });
    });

    conn.connect({
      host,
      port: port ?? 22,
      username,
      privateKey,
    });
  });

  return p;
});

const transport = new StdioServerTransport();
await server.connect(transport);
