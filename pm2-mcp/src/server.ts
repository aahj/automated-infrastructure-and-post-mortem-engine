import { createMcpFastifyApp } from '@modelcontextprotocol/fastify';
import { toNodeHandler } from '@modelcontextprotocol/node';
import { createMcpHandler } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import type { FastifyInstance } from 'fastify';
import { authorizeToken } from './auth.js';
import type { ServerConfig } from './config.js';
import { Pm2Client } from './pm2-client.js';
import { createMcpServer } from './tools.js';

export type RunningServer = { close(): Promise<void> };

function createHttpApp(config: ServerConfig, pm2: Pm2Client): FastifyInstance {
    const app = createMcpFastifyApp({
        host: config.host,
        allowedHosts: config.allowedHosts,
        allowedOrigins: config.allowedHosts,
    });
    app.addHook('onRequest', async (request, reply) => {
        const origin = request.headers.origin;
        if (origin === undefined) return;
        const hostHeader = request.headers.host;
        try {
            if (typeof origin !== 'string' || typeof hostHeader !== 'string') throw new Error('Invalid origin');
            const host = new URL(`http://${hostHeader}`);
            const parsedOrigin = new URL(origin);
            if (
                parsedOrigin.protocol !== 'http:' ||
                parsedOrigin.hostname.toLowerCase() !== host.hostname.toLowerCase() ||
                parsedOrigin.username ||
                parsedOrigin.password ||
                parsedOrigin.pathname !== '/' ||
                parsedOrigin.search ||
                parsedOrigin.hash
            )
                throw new Error('Origin does not match Host');
        } catch {
            console.warn('[pm2-mcp] request.denied reason=origin_validation');
            await reply.code(403).send({ error: 'Forbidden' });
        }
    });

    app.all(config.path, async (request, reply) => {
        let access;
        try {
            access = authorizeToken(request.headers.authorization, config);
        } catch {
            console.warn(`[pm2-mcp] request.denied method=${request.method} reason=invalid_bearer`);
            return reply.code(401).header('www-authenticate', 'Bearer').send({ error: 'Unauthorized' });
        }

        const handler = createMcpHandler(() => createMcpServer(pm2, access, config), { legacy: 'stateless' });
        const nodeHandler = toNodeHandler(handler);
        reply.hijack();
        try {
            await nodeHandler(request.raw, reply.raw, request.body);
        } finally {
            await handler.close();
        }
    });

    return app;
}

export async function createServer(
    config: ServerConfig,
    client = new Pm2Client(undefined, config.allowDaemonStart, config.pm2Home),
): Promise<RunningServer> {
    await client.connect();
    if (config.mode === 'stdio') {
        const access = process.env.PM2_MCP_STDIO_ACCESS === 'write' ? 'write' : 'read';
        const stdio = serveStdio(() => createMcpServer(client, access, config));
        let closePromise: Promise<void> | undefined;
        return {
            close: () => {
                closePromise ??= (async () => {
                    await stdio.close();
                    await client.close();
                })();
                return closePromise;
            },
        };
    }

    const app = createHttpApp(config, client);
    try {
        await app.listen({ port: config.port, host: config.host });
    } catch (error) {
        try {
            await app.close();
        } finally {
            await client.close();
        }
        throw error;
    }
    let closePromise: Promise<void> | undefined;
    return {
        close: () => {
            closePromise ??= (async () => {
                try {
                    await app.close();
                } finally {
                    await client.close();
                }
            })();
            return closePromise;
        },
    };
}
