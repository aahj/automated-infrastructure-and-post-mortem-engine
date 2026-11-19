import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';
import type { ServerConfig } from '../src/config.js';
import type { Pm2Client } from '../src/pm2-client.js';

test('stdio server closes the MCP transport and PM2 connection on shutdown', async () => {
    const config: ServerConfig = {
        mode: 'stdio',
        host: '0.0.0.0',
        port: 8486,
        path: '/mcp',
        allowedHosts: [],
        pm2Home: 'C:/pm2-test',
        allowDaemonStart: false,
        readToken: 'r'.repeat(32),
        writeToken: 'w'.repeat(32),
        startTargets: {},
    };
    let closes = 0;
    const fakePm2 = {
        connect: async () => undefined,
        close: async () => {
            closes += 1;
        },
    } as unknown as Pm2Client;
    const running = await createServer(config, fakePm2);
    await running.close();
    assert.equal(closes, 1);
});
