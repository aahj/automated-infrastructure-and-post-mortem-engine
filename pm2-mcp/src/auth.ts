import { createHash, timingSafeEqual } from 'node:crypto';

export type AccessLevel = 'read' | 'write';
export type TokenConfig = { readToken: string; writeToken: string };

function matches(candidate: string, expected: string): boolean {
    const a = createHash('sha256').update(candidate).digest();
    const b = createHash('sha256').update(expected).digest();
    return timingSafeEqual(a, b);
}

export function authorizeToken(header: string | undefined, config: TokenConfig): AccessLevel {
    const match = header?.match(/^Bearer ([^\s]+)$/);
    if (!match) throw new Error('Unauthorized');
    const read = matches(match[1], config.readToken);
    const write = matches(match[1], config.writeToken);
    if (write) return 'write';
    if (read) return 'read';
    throw new Error('Unauthorized');
}
