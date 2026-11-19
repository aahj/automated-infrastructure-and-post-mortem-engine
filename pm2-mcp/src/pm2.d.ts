declare module 'pm2' {
    type Callback<T = unknown> = (error: Error | null, result?: T) => void;
    type Pm2Instance = {
        connect(noDaemonMode: boolean, callback: (error: Error | null) => void): void;
        disconnect(callback?: () => void): void;
        list(callback: Callback<unknown[]>): void;
        describe(name: string, callback: Callback<unknown[]>): void;
        start(process: unknown, callback: Callback): void;
        stop(name: string, callback: Callback): void;
        restart(name: string, callback: Callback): void;
        reload(name: string, callback: Callback): void;
    };
    const pm2: Pm2Instance & {
        custom: new (options: { pm2_home: string; cwd: string }) => Pm2Instance;
    };
    export default pm2;
}
