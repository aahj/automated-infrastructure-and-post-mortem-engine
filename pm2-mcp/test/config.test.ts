import test from 'node:test';
import assert from 'node:assert/strict';
import { loadConfig } from '../src/config.js';

test('requires an explicit PM2 home and separate strong tokens', () => {
    assert.throws(() => loadConfig({}), /PM2_HOME/);
    const env = {
        PM2_HOME: 'C:/pm2-test',
        PM2_MCP_READ_TOKEN: 'r'.repeat(32),
        PM2_MCP_WRITE_TOKEN: 'w'.repeat(32),
    };
    assert.equal(loadConfig(env).host, '0.0.0.0');
    assert.equal(loadConfig(env).port, 8486);
});

test('stdio mode requires PM2_HOME but does not require HTTP bearer tokens', () => {
    const config = loadConfig({ PM2_HOME: 'C:/pm2-test', PM2_MCP_TRANSPORT: 'stdio' });

    assert.equal(config.mode, 'stdio');
    assert.equal(config.readToken, '');
    assert.equal(config.writeToken, '');
});

test('HTTP mode still requires distinct strong bearer tokens', () => {
    assert.throws(
        () => loadConfig({ PM2_HOME: 'C:/pm2-test' }),
        /PM2 MCP read and write tokens must be distinct and at least 32 characters/,
    );
});
