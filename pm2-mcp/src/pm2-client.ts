import pm2 from 'pm2';

export type ServiceSummary = { name: string; status: string; pid: number | null; restarts: number };
export type ServiceDetails = ServiceSummary & { cpu: number | null; memory: number | null };

export type Pm2Api = {
    connect(noDaemonMode: boolean, callback: (error: Error | null) => void): void;
    disconnect(callback?: () => void): void;
    list(callback: (error: Error | null, result?: unknown[]) => void): void;
    describe(name: string, callback: (error: Error | null, result?: unknown[]) => void): void;
    start(process: unknown, callback: (error: Error | null, result?: unknown) => void): void;
    stop(name: string, callback: (error: Error | null, result?: unknown) => void): void;
    restart(name: string, callback: (error: Error | null, result?: unknown) => void): void;
    reload(name: string, callback: (error: Error | null, result?: unknown) => void): void;
};
type RawProcess = {
    name?: string;
    pm2_env?: { status?: string; restart_time?: number };
    pid?: number;
    monit?: { cpu?: number; memory?: number };
};

function invoke<T>(api: Pm2Api, method: string, ...args: unknown[]): Promise<T> {
    return new Promise((resolve, reject) => {
        const fn = (api as unknown as Record<string, (...values: unknown[]) => void>)[method];
        fn.call(api, ...args, (error: Error | null, result: T) => (error ? reject(error) : resolve(result)));
    });
}

function summarize(raw: RawProcess): ServiceDetails {
    return {
        name: raw.name ?? 'unknown',
        status: raw.pm2_env?.status ?? 'unknown',
        pid: typeof raw.pid === 'number' && raw.pid > 0 ? raw.pid : null,
        restarts: raw.pm2_env?.restart_time ?? 0,
        cpu: raw.monit?.cpu ?? null,
        memory: raw.monit?.memory ?? null,
    };
}

export class Pm2Client {
    private connected = false;
    private closed = false;
    private readonly api: Pm2Api;

    constructor(
        api?: Pm2Api,
        private readonly allowDaemonStart = false,
        pm2Home = process.env.PM2_HOME,
    ) {
        if (api) {
            this.api = api;
        } else {
            if (!pm2Home) throw new Error('PM2_HOME is required to create the PM2 API client');
            this.api = new pm2.custom({ pm2_home: pm2Home, cwd: process.cwd() }) as Pm2Api;
        }
    }

    async connect(): Promise<void> {
        if (this.connected) return;
        // PM2's no-daemon mode prevents silently creating a persistent daemon by default.
        console.error('[pm2-mcp] pm2.connecting');
        await new Promise<void>((resolve, reject) => {
            this.api.connect(!this.allowDaemonStart, (error: Error | null) => (error ? reject(error) : resolve()));
        });
        this.connected = true;
        console.error('[pm2-mcp] pm2.connected');
    }

    async listServices(): Promise<ServiceSummary[]> {
        const rows = await invoke<RawProcess[]>(this.api, 'list');
        return rows.map(summarize).map(({ name, status, pid, restarts }) => ({ name, status, pid, restarts }));
    }

    async getStatus(name: string): Promise<ServiceDetails> {
        const rows = await invoke<RawProcess[]>(this.api, 'describe', name);
        if (!rows.length) throw new Error(`PM2 service not found: ${name}`);
        return summarize(rows[0]);
    }

    async startService(
        name: string,
        definition: { script: string; cwd?: string; args?: string[] },
    ): Promise<ServiceDetails> {
        const options: { name: string; script: string; cwd?: string; args?: string[] } = {
            name,
            script: definition.script,
        };
        if (definition.cwd !== undefined) options.cwd = definition.cwd;
        if (definition.args !== undefined) options.args = [...definition.args];
        await invoke(this.api, 'start', options);
        return this.getStatus(name);
    }

    async stopService(name: string): Promise<ServiceDetails> {
        await invoke(this.api, 'stop', name);
        return this.getStatus(name);
    }

    async restartService(name: string): Promise<ServiceDetails> {
        await invoke(this.api, 'restart', name);
        return this.getStatus(name);
    }

    async reloadService(name: string): Promise<ServiceDetails> {
        await invoke(this.api, 'reload', name);
        return this.getStatus(name);
    }

    async close(): Promise<void> {
        if (!this.connected || this.closed) return;
        this.closed = true;
        await new Promise<void>((resolve) => this.api.disconnect(() => resolve()));
        console.error('[pm2-mcp] pm2.disconnected');
    }
}
