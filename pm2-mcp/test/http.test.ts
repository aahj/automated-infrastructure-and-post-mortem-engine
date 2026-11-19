import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';
import type { ServerConfig } from '../src/config.js';
import type { Pm2Client } from '../src/pm2-client.js';
import { createServer as createNetServer } from 'node:net';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';

async function unusedPort(): Promise<number> {
    const server = createNetServer();
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('No test port allocated');
    const port = address.port;
    await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    return port;
}

test('authenticates each session, scopes tools by token, and keeps listener alive between sessions', async () => {
    const port = await unusedPort();
    const config: ServerConfig = {
        mode: 'http',
        host: '127.0.0.1',
        port,
        path: '/mcp',
        allowedHosts: ['127.0.0.1'],
        pm2Home: 'test-home',
        allowDaemonStart: false,
        readToken: 'r'.repeat(32),
        writeToken: 'w'.repeat(32),
        startTargets: { approved: { script: 'fixture.js' } },
    };
    let closes = 0;
    let starts = 0;
    const fakePm2 = {
        connect: async () => undefined,
        close: async () => {
            closes += 1;
        },
        listServices: async () => [],
        getStatus: async (name: string) => ({ name, status: 'online', pid: 1, restarts: 0, cpu: 0, memory: 0 }),
        startService: async (name: string) => {
            starts += 1;
            return { name, status: 'online', pid: 1, restarts: 0, cpu: 0, memory: 0 };
        },
        stopService: async (name: string) => ({
            name,
            status: 'stopped',
            pid: null,
            restarts: 0,
            cpu: null,
            memory: null,
        }),
        restartService: async (name: string) => ({ name, status: 'online', pid: 1, restarts: 0, cpu: 0, memory: 0 }),
        reloadService: async (name: string) => ({ name, status: 'online', pid: 1, restarts: 0, cpu: 0, memory: 0 }),
    } as unknown as Pm2Client;
    const running = await createServer(config, fakePm2);
    try {
        const first = await fetch(`http://127.0.0.1:${port}/mcp`, { method: 'POST', body: '{}' });
        assert.equal(first.status, 401);
        const invalidToken = await fetch(`http://127.0.0.1:${port}/mcp`, {
            method: 'POST',
            headers: { Authorization: 'Bearer invalid-token' },
            body: '{}',
        });
        assert.equal(invalidToken.status, 401);
        const badOrigin = await fetch(`http://127.0.0.1:${port}/mcp`, {
            method: 'POST',
            headers: { Origin: 'http://attacker.invalid' },
            body: '{}',
        });
        assert.equal(badOrigin.status, 403);
        async function listTools(token: string, negotiateModern = false) {
            const client = new Client(
                { name: 'pm2-mcp-test', version: '1.0.0' },
                negotiateModern ? { versionNegotiation: { mode: 'auto' } } : undefined,
            );
            const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`), {
                requestInit: { headers: { Authorization: `Bearer ${token}` } },
            });
            await client.connect(transport);
            try {
                return (await client.listTools()).tools.map((tool) => tool.name);
            } finally {
                await client.close();
            }
        }
        const readTools = await listTools(config.readToken);
        assert.deepEqual(readTools, ['list_services', 'get_status']);
        const reader = new Client({ name: 'pm2-mcp-test', version: '1.0.0' });
        await reader.connect(
            new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`), {
                requestInit: { headers: { Authorization: `Bearer ${config.readToken}` } },
            }),
        );
        const listed = await reader.callTool({ name: 'list_services', arguments: {} });
        assert.deepEqual(listed.structuredContent, { services: [] });
        await reader.close();
        const modernReadTools = await listTools(config.readToken, true);
        assert.deepEqual(modernReadTools, ['list_services', 'get_status']);
        assert.equal(closes, 0);
        const writeTools = await listTools(config.writeToken);
        assert.ok(writeTools.includes('start_service'));
        assert.ok(writeTools.includes('stop_service'));
        assert.ok(writeTools.includes('restart_service'));
        assert.ok(writeTools.includes('reload_service'));
        assert.equal(closes, 0);
        const writer = new Client({ name: 'pm2-mcp-test', version: '1.0.0' });
        await writer.connect(
            new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`), {
                requestInit: { headers: { Authorization: `Bearer ${config.writeToken}` } },
            }),
        );
        const deniedStart = await writer.callTool({ name: 'start_service', arguments: { name: 'unapproved' } });
        assert.equal(deniedStart.isError, true);
        assert.equal(starts, 0);
        const allowedStart = await writer.callTool({ name: 'start_service', arguments: { name: 'approved' } });
        assert.equal(allowedStart.isError, undefined);
        assert.equal(starts, 1);
        await writer.close();
        assert.equal(closes, 0);
    } finally {
        await running.close();
    }
    assert.equal(closes, 1);
});
