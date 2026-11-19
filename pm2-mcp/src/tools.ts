import { McpServer } from '@modelcontextprotocol/server';
import { z } from 'zod';
import type { AccessLevel } from './auth.js';
import type { ServerConfig } from './config.js';
import type { Pm2Client } from './pm2-client.js';

const serviceSummarySchema = z.object({
    name: z.string(),
    status: z.string(),
    pid: z.number().int().nullable(),
    restarts: z.number().int(),
});
const serviceDetailsSchema = serviceSummarySchema.extend({
    cpu: z.number().nullable(),
    memory: z.number().nullable(),
});

async function withToolLogging<T>(name: string, action: () => Promise<T>): Promise<T> {
    const startedAt = Date.now();
    console.error(`[pm2-mcp] tool.started name=${name}`);
    try {
        const result = await action();
        console.error(`[pm2-mcp] tool.completed name=${name} duration_ms=${Date.now() - startedAt}`);
        return result;
    } catch (error) {
        const errorName = error instanceof Error ? error.name : 'UnknownError';
        console.error(`[pm2-mcp] tool.failed name=${name} duration_ms=${Date.now() - startedAt} error=${errorName}`);
        throw error;
    }
}

export function normalizeTarget(input: string): string {
    const name = input.trim();
    if (!name || ['*', 'all'].includes(name.toLowerCase())) {
        throw new Error('A concrete service name is required');
    }
    return name;
}

function register(server: McpServer, pm2: Pm2Client, access: AccessLevel, config: ServerConfig): void {
    server.registerTool(
        'list_services',
        {
            description: 'List PM2 managed services',
            inputSchema: z.object({}),
            outputSchema: z.object({ services: z.array(serviceSummarySchema) }),
        },
        async () =>
            withToolLogging('list_services', async () => {
                const services = await pm2.listServices();
                return {
                    content: [{ type: 'text', text: JSON.stringify(services) }],
                    structuredContent: { services },
                };
            }),
    );
    server.registerTool(
        'get_status',
        {
            description: 'Get status for one PM2 service',
            inputSchema: z.object({ name: z.string().min(1).max(128) }),
            outputSchema: serviceDetailsSchema,
        },
        async ({ name }) =>
            withToolLogging('get_status', async () => {
                const service = await pm2.getStatus(normalizeTarget(name));
                return {
                    content: [{ type: 'text', text: JSON.stringify(service) }],
                    structuredContent: service,
                };
            }),
    );
    if (access !== 'write') return;
    const mutationSchema = z.object({ name: z.string().min(1).max(128) });
    server.registerTool(
        'start_service',
        {
            description: 'Start one allowlisted PM2 service',
            inputSchema: mutationSchema,
            outputSchema: serviceDetailsSchema,
        },
        async ({ name }) =>
            withToolLogging('start_service', async () => {
                const target = normalizeTarget(name);
                const definition = config.startTargets[target];
                if (!definition) throw new Error(`Service is not allowlisted for start: ${target}`);
                const service = await pm2.startService(target, definition);
                return {
                    content: [{ type: 'text', text: JSON.stringify(service) }],
                    structuredContent: service,
                };
            }),
    );
    for (const [toolName, method] of [
        ['stop_service', pm2.stopService.bind(pm2)],
        ['restart_service', pm2.restartService.bind(pm2)],
        ['reload_service', pm2.reloadService.bind(pm2)],
    ] as const) {
        server.registerTool(
            toolName,
            {
                description: `Run ${toolName.replace('_', ' ')} for one PM2 service`,
                inputSchema: mutationSchema,
                outputSchema: serviceDetailsSchema,
            },
            async ({ name }) =>
                withToolLogging(toolName, async () => {
                    const target = normalizeTarget(name);
                    const current = await pm2.getStatus(target);
                    if (!current.name || current.name !== target) {
                        throw new Error(`PM2 service not found: ${target}`);
                    }
                    const service = await method(target);
                    return {
                        content: [{ type: 'text', text: JSON.stringify(service) }],
                        structuredContent: service,
                    };
                }),
        );
    }
}

export function createMcpServer(pm2: Pm2Client, access: AccessLevel, config: ServerConfig): McpServer {
    const server = new McpServer({ name: 'owned-pm2-mcp', version: '0.1.0' });
    register(server, pm2, access, config);
    return server;
}
