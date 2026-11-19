import { isIP } from 'node:net';
import { isAbsolute as isPosixAbsolute, win32 } from 'node:path';

export type ServerConfig = {
    mode: 'http' | 'stdio';
    host: string;
    port: number;
    path: string;
    allowedHosts: string[];
    pm2Home: string;
    allowDaemonStart: boolean;
    readToken: string;
    writeToken: string;
    startTargets: Record<string, { script: string; cwd?: string; args?: string[] }>;
};

function required(env: NodeJS.ProcessEnv, key: string): string {
    const value = env[key]?.trim();
    if (!value) throw new Error(`${key} is required`);
    return value;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ServerConfig {
    const pm2Home = required(env, 'PM2_HOME');
    const mode = env.PM2_MCP_TRANSPORT ?? 'http';
    if (!['http', 'streamable_http', 'stdio'].includes(mode)) throw new Error('Invalid PM2_MCP_TRANSPORT');
    const readToken = env.PM2_MCP_READ_TOKEN?.trim() ?? '';
    const writeToken = env.PM2_MCP_WRITE_TOKEN?.trim() ?? '';
    if (mode !== 'stdio' && (readToken.length < 32 || writeToken.length < 32 || readToken === writeToken)) {
        throw new Error('PM2 MCP read and write tokens must be distinct and at least 32 characters');
    }
    let startTargets: ServerConfig['startTargets'] = {};
    try {
        const raw = env.PM2_MCP_START_TARGETS_JSON;
        if (raw) {
            const parsed: unknown = JSON.parse(raw);
            if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error();
            startTargets = parsed as ServerConfig['startTargets'];
            for (const [name, target] of Object.entries(startTargets)) {
                if (!name.trim() || !target || typeof target.script !== 'string' || !target.script.trim()) {
                    throw new Error();
                }
                if (target.cwd !== undefined && typeof target.cwd !== 'string') throw new Error();
                if (
                    target.args &&
                    (!Array.isArray(target.args) || !target.args.every((arg) => typeof arg === 'string'))
                )
                    throw new Error();
            }
        }
    } catch {
        throw new Error('PM2_MCP_START_TARGETS_JSON must map names to script definitions');
    }
    const port = Number(env.PM2_MCP_PORT ?? 8486);
    const path = env.PM2_MCP_PATH ?? '/mcp';
    const host = env.PM2_MCP_HOST ?? '0.0.0.0';
    const allowDaemonStart = env.PM2_MCP_ALLOW_DAEMON_START ?? 'false';
    if (!isPosixAbsolute(pm2Home) && !win32.isAbsolute(pm2Home)) {
        throw new Error('PM2_HOME must be an absolute path');
    }
    if (!host || /[\s/\\]/.test(host) || (!isIP(host) && !/^[a-zA-Z0-9.-]+$/.test(host))) {
        throw new Error('Invalid PM2_MCP_HOST');
    }
    if (!['true', 'false'].includes(allowDaemonStart)) throw new Error('Invalid PM2_MCP_ALLOW_DAEMON_START');
    const allowedHosts = (env.PM2_MCP_ALLOWED_HOSTS ?? 'localhost,127.0.0.1,host.docker.internal')
        .split(',')
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean);
    if (
        !allowedHosts.length ||
        allowedHosts.some(
            (allowedHost) => /[\s/:\\]/.test(allowedHost) || (!isIP(allowedHost) && !/^[a-z0-9.-]+$/.test(allowedHost)),
        )
    ) {
        throw new Error('PM2_MCP_ALLOWED_HOSTS must be a comma-separated list of hostnames');
    }
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid PM2_MCP_PORT');
    if (!path.startsWith('/') || path.includes('?') || path.includes('#')) {
        throw new Error('PM2_MCP_PATH must be an absolute URL path');
    }
    return {
        mode: mode === 'stdio' ? 'stdio' : 'http',
        host,
        port,
        path,
        allowedHosts,
        pm2Home,
        allowDaemonStart: allowDaemonStart === 'true',
        readToken,
        writeToken,
        startTargets,
    };
}
