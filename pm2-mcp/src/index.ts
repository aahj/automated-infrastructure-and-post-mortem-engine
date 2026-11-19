import 'dotenv/config';
import { loadConfig } from './config.js';
import { createServer } from './server.js';

async function main(): Promise<void> {
    const config = loadConfig();
    console.error(`[pm2-mcp] starting transport=${config.mode}`);
    const running = await createServer(config);
    if (config.mode === 'http') {
        console.error(`[pm2-mcp] listening url=http://${config.host}:${config.port}${config.path}`);
    } else {
        console.error('[pm2-mcp] ready transport=stdio');
    }
    let shuttingDown = false;
    const shutdown = async (signal: NodeJS.Signals) => {
        if (shuttingDown) return;
        shuttingDown = true;
        console.error(`[pm2-mcp] shutdown.started signal=${signal}`);
        try {
            await running.close();
            console.error('[pm2-mcp] shutdown.completed');
        } catch (error) {
            const message = error instanceof Error ? error.message : 'unknown error';
            console.error(`[pm2-mcp] shutdown.failed error=${message}`);
            process.exitCode = 1;
        }
    };
    process.once('SIGINT', () => void shutdown('SIGINT'));
    process.once('SIGTERM', () => void shutdown('SIGTERM'));
}

main().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : 'unknown error';
    console.error(`[pm2-mcp] startup.failed error=${message}`);
    process.exitCode = 1;
});
