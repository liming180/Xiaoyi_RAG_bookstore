import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/** Node 侧 MSW：vitest 用 */
export const server = setupServer(...handlers);
