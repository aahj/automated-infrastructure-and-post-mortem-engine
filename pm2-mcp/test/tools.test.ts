import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeTarget } from '../src/tools.js';

test('rejects empty and wildcard service names', () => {
    for (const name of ['', '*', 'all', ' ALL ']) {
        assert.throws(() => normalizeTarget(name));
    }
});

test('normalizes a concrete service name', () => {
    assert.equal(normalizeTarget(' api '), 'api');
});
