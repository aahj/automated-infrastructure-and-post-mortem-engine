import test from 'node:test';
import assert from 'node:assert/strict';
import { authorizeToken } from '../src/auth.js';

test('requires an exact configured bearer token and grants its role', () => {
    const config = { readToken: 'r'.repeat(32), writeToken: 'w'.repeat(32) };
    assert.equal(authorizeToken(`Bearer ${config.readToken}`, config), 'read');
    assert.equal(authorizeToken(`Bearer ${config.writeToken}`, config), 'write');
    assert.throws(() => authorizeToken(undefined, config), /Unauthorized/);
    assert.throws(() => authorizeToken('Basic abc', config), /Unauthorized/);
    assert.throws(() => authorizeToken('Bearer wrong', config), /Unauthorized/);
});
