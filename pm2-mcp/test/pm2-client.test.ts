import 'dotenv/config';
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Pm2Client } from '../src/pm2-client.js';

test('maps PM2 list, describe and lifecycle API calls to normalized data', async () => {
    const record = {
        name: 'api',
        pid: 42,
        pm2_env: { status: 'online', restart_time: 2 },
        monit: { cpu: 3, memory: 512 },
    };
    const calls: string[] = [];
    let noDaemonMode: boolean | undefined;
    const api = {
        list: (cb: (err: null, result: unknown[]) => void) => {
            calls.push('list');
            cb(null, [record]);
        },
        describe: (_name: string, cb: (err: null, result: unknown[]) => void) => {
            calls.push('describe');
            cb(null, [record]);
        },
        start: (_options: unknown, cb: (err: null) => void) => {
            calls.push('start');
            cb(null);
        },
        stop: (_name: string, cb: (err: null) => void) => {
            calls.push('stop');
            cb(null);
        },
        restart: (_name: string, cb: (err: null) => void) => {
            calls.push('restart');
            cb(null);
        },
        reload: (_name: string, cb: (err: null) => void) => {
            calls.push('reload');
            cb(null);
        },
        connect: (noDaemon: boolean, cb: (err: null) => void) => {
            noDaemonMode = noDaemon;
            cb(null);
        },
        disconnect: (cb: () => void) => cb(),
    };
    const client = new Pm2Client(api as never);
    await client.connect();
    assert.equal(noDaemonMode, true);
    assert.deepEqual(await client.listServices(), [{ name: 'api', status: 'online', pid: 42, restarts: 2 }]);
    assert.equal((await client.getStatus('api')).memory, 512);
    await client.startService('api', { script: 'api.js' });
    await client.stopService('api');
    await client.restartService('api');
    await client.reloadService('api');
    await client.close();
    assert.deepEqual(calls, [
        'list',
        'describe',
        'start',
        'describe',
        'stop',
        'describe',
        'restart',
        'describe',
        'reload',
        'describe',
    ]);
});

test('surfaces PM2 API errors to the caller', async () => {
    const failure = new Error('PM2 daemon unavailable');
    const api = {
        connect: (_noDaemon: boolean, callback: (error: null) => void) => callback(null),
        list: (callback: (error: Error) => void) => callback(failure),
        disconnect: (callback: () => void) => callback(),
    };
    const client = new Pm2Client(api as never);
    await client.connect();
    await assert.rejects(client.listServices(), /PM2 daemon unavailable/);
    await client.close();
});

test(
    'real PM2 fixture lifecycle is opt-in and isolated to a temporary PM2_HOME',
    { skip: process.env.RUN_PM2_INTEGRATION !== '1' },
    async () => {
        const home = await mkdtemp(join(tmpdir(), 'owned-pm2-mcp-'));
        const client = new Pm2Client(undefined, false, home);
        try {
            await client.connect();
            const fixture = join(
                fileURLToPath(new URL('.', import.meta.url)),
                '..',
                '..',
                'test',
                'fixtures',
                'fixture-process.js',
            );
            await client.startService('owned-pm2-fixture', { script: fixture });
            assert.ok((await client.listServices()).some((service) => service.name === 'owned-pm2-fixture'));
            await client.stopService('owned-pm2-fixture');
        } finally {
            try {
                await client.stopService('owned-pm2-fixture');
            } catch {
                /* fixture may not have started */
            }
            await client.close();
            await rm(home, { recursive: true, force: true });
        }
    },
);
