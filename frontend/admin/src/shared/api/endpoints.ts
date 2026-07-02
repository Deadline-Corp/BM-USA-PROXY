import { apiClient } from "@/shared/api/client";
import type {
  Admin,
  AdminAccount,
  AdminAccountInput,
  AppSettings,
  AuditLogEntry,
  Broadcast,
  BroadcastInput,
  BroadcastProgress,
  Channel,
  Client,
  ClientDossier,
  Connection,
  ConnectionUpdate,
  DashboardSummary,
  FaqItem,
  IssueAccessRequest,
  ListParams,
  LoginRequest,
  LoginResponse,
  MarkPaidRequest,
  NotificationLogEntry,
  NotificationSettingEntry,
  Order,
  Paginated,
  Payout,
  PoolSummary,
  Post,
  PostAttribution,
  RefreshResponse,
  RefundRequest,
  ReferralLedgerEntry,
  ReferralSettings,
  ReferralSummary,
  ResolveOrderRequest,
  RevenuePoint,
  SupportRequest,
  Tariff,
  TariffInput,
  Terms,
  AccessRow,
} from "@/shared/api/types";

// Thin, typed wrappers around every endpoint in the task spec. Grouped by
// resource. Every list endpoint accepts a ListParams bag and returns
// Paginated<T> — pagination/filtering lives in the DataTable + hooks layer.

// ---------- Auth ----------

export const authApi = {
  login: (body: LoginRequest) =>
    apiClient.post<LoginResponse>("/auth/login", body).then((r) => r.data),
  refresh: () =>
    apiClient.post<RefreshResponse>("/auth/refresh").then((r) => r.data),
  logout: () => apiClient.post<void>("/auth/logout").then((r) => r.data),
  me: () => apiClient.get<Admin>("/me").then((r) => r.data),
};

// ---------- Dashboard ----------

export const dashboardApi = {
  summary: () =>
    apiClient.get<DashboardSummary>("/dashboard").then((r) => r.data),
  revenue: (days = 30) =>
    apiClient
      .get<RevenuePoint[]>("/dashboard/revenue", { params: { days } })
      .then((r) => r.data),
};

// ---------- Clients ----------

export const clientsApi = {
  list: (params: ListParams) =>
    apiClient
      .get<Paginated<Client>>("/clients", { params })
      .then((r) => r.data),
  get: (id: string) =>
    apiClient.get<ClientDossier>(`/clients/${id}`).then((r) => r.data),
  updateNote: (id: string, operator_note: string) =>
    apiClient
      .patch<Client>(`/clients/${id}`, { operator_note })
      .then((r) => r.data),
  ban: (id: string) =>
    apiClient.post<Client>(`/clients/${id}/ban`).then((r) => r.data),
  unban: (id: string) =>
    apiClient.post<Client>(`/clients/${id}/unban`).then((r) => r.data),
  message: (id: string, text: string) =>
    apiClient.post<void>(`/clients/${id}/message`, { text }).then((r) => r.data),
  issueAccess: (id: string, body: IssueAccessRequest) =>
    apiClient
      .post<ClientDossier>(`/clients/${id}/issue-access`, body)
      .then((r) => r.data),
};

// ---------- Tariffs ----------

export const tariffsApi = {
  list: () => apiClient.get<Tariff[]>("/tariffs").then((r) => r.data),
  create: (body: TariffInput) =>
    apiClient.post<Tariff>("/tariffs", body).then((r) => r.data),
  update: (id: string, body: Partial<TariffInput>) =>
    apiClient.patch<Tariff>(`/tariffs/${id}`, body).then((r) => r.data),
  toggle: (id: string) =>
    apiClient.post<Tariff>(`/tariffs/${id}/toggle`).then((r) => r.data),
};

// ---------- Pool / Connections ----------

export const poolApi = {
  listConnections: (params: ListParams) =>
    apiClient
      .get<Paginated<Connection>>("/connections", { params })
      .then((r) => r.data),
  updateConnection: (id: string, body: ConnectionUpdate) =>
    apiClient.patch<Connection>(`/connections/${id}`, body).then((r) => r.data),
  sync: () => apiClient.post<void>("/connections/sync").then((r) => r.data),
  summary: () => apiClient.get<PoolSummary>("/pool/summary").then((r) => r.data),
};

// ---------- Packages / Accesses ----------

export const accessesApi = {
  list: (params: ListParams) =>
    apiClient
      .get<Paginated<AccessRow>>("/accesses", { params })
      .then((r) => r.data),
  revoke: (id: string, reason: string) =>
    apiClient
      .post<AccessRow>(`/accesses/${id}/revoke`, { reason })
      .then((r) => r.data),
  extend: (id: string, minutes: number) =>
    apiClient
      .post<AccessRow>(`/accesses/${id}/extend`, { minutes })
      .then((r) => r.data),
  rotateIp: (id: string) =>
    apiClient.post<AccessRow>(`/accesses/${id}/rotate-ip`).then((r) => r.data),
  reissue: (id: string, connection_id?: string) =>
    apiClient
      .post<AccessRow>(`/accesses/${id}/reissue`, { connection_id })
      .then((r) => r.data),
};

// ---------- Orders / Payments ----------

export const ordersApi = {
  list: (params: ListParams) =>
    apiClient.get<Paginated<Order>>("/orders", { params }).then((r) => r.data),
  get: (id: string) => apiClient.get<Order>(`/orders/${id}`).then((r) => r.data),
  manualReview: () =>
    apiClient.get<Paginated<Order>>("/payments/manual-review").then((r) => r.data),
  resolve: (id: string, body: ResolveOrderRequest) =>
    apiClient.post<Order>(`/orders/${id}/resolve`, body).then((r) => r.data),
  refund: (id: string, body: RefundRequest) =>
    apiClient.post<Order>(`/orders/${id}/refund`, body).then((r) => r.data),
  markPaid: (id: string, body: MarkPaidRequest) =>
    apiClient.post<Order>(`/orders/${id}/mark-paid`, body).then((r) => r.data),
};

// ---------- Requests ----------

export const requestsApi = {
  list: (status?: string) =>
    apiClient
      .get<Paginated<SupportRequest>>("/requests", { params: { status } })
      .then((r) => r.data),
  update: (id: string, body: Partial<Pick<SupportRequest, "status" | "assignee_id">>) =>
    apiClient.patch<SupportRequest>(`/requests/${id}`, body).then((r) => r.data),
  addComment: (id: string, body: string) =>
    apiClient
      .post<void>(`/requests/${id}/comments`, { body })
      .then((r) => r.data),
};

// ---------- Referrals ----------

export const referralsApi = {
  summary: () =>
    apiClient.get<ReferralSummary>("/referrals/summary").then((r) => r.data),
  ledger: (params: ListParams) =>
    apiClient
      .get<Paginated<ReferralLedgerEntry>>("/referrals/ledger", { params })
      .then((r) => r.data),
  payouts: (status?: string) =>
    apiClient
      .get<Paginated<Payout>>("/payouts", { params: { status } })
      .then((r) => r.data),
  approvePayout: (id: string) =>
    apiClient.post<Payout>(`/payouts/${id}/approve`).then((r) => r.data),
  rejectPayout: (id: string, reason: string) =>
    apiClient.post<Payout>(`/payouts/${id}/reject`, { reason }).then((r) => r.data),
  markPayoutPaid: (id: string, tx_hash: string) =>
    apiClient
      .post<Payout>(`/payouts/${id}/mark-paid`, { tx_hash })
      .then((r) => r.data),
  getSettings: () =>
    apiClient.get<ReferralSettings>("/settings/referral").then((r) => r.data),
  updateSettings: (body: Partial<ReferralSettings>) =>
    apiClient.patch<ReferralSettings>("/settings/referral", body).then((r) => r.data),
};

// ---------- Broadcasts ----------

export const broadcastsApi = {
  list: () => apiClient.get<Paginated<Broadcast>>("/broadcasts").then((r) => r.data),
  create: (body: BroadcastInput) =>
    apiClient.post<Broadcast>("/broadcasts", body).then((r) => r.data),
  update: (id: string, body: Partial<BroadcastInput>) =>
    apiClient.patch<Broadcast>(`/broadcasts/${id}`, body).then((r) => r.data),
  schedule: (id: string, scheduled_at: string) =>
    apiClient
      .post<Broadcast>(`/broadcasts/${id}/schedule`, { scheduled_at })
      .then((r) => r.data),
  sendNow: (id: string) =>
    apiClient.post<Broadcast>(`/broadcasts/${id}/send-now`).then((r) => r.data),
  progress: (id: string) =>
    apiClient
      .get<BroadcastProgress>(`/broadcasts/${id}/progress`)
      .then((r) => r.data),
};

// ---------- Publications ----------

export const publicationsApi = {
  listChannels: () => apiClient.get<Channel[]>("/channels").then((r) => r.data),
  createChannel: (body: Omit<Channel, "id">) =>
    apiClient.post<Channel>("/channels", body).then((r) => r.data),
  updateChannel: (id: string, body: Partial<Omit<Channel, "id">>) =>
    apiClient.patch<Channel>(`/channels/${id}`, body).then((r) => r.data),
  listPosts: (params: ListParams) =>
    apiClient.get<Paginated<Post>>("/posts", { params }).then((r) => r.data),
  createPost: (body: Omit<Post, "id" | "status" | "published_at" | "views" | "clicks">) =>
    apiClient.post<Post>("/posts", body).then((r) => r.data),
  updatePost: (id: string, body: Partial<Post>) =>
    apiClient.patch<Post>(`/posts/${id}`, body).then((r) => r.data),
  publishPost: (id: string) =>
    apiClient.post<Post>(`/posts/${id}/publish`).then((r) => r.data),
  attribution: (id: string) =>
    apiClient.get<PostAttribution>(`/posts/${id}/attribution`).then((r) => r.data),
};

// ---------- FAQ ----------

export const faqApi = {
  list: () => apiClient.get<FaqItem[]>("/faq").then((r) => r.data),
  create: (body: Omit<FaqItem, "id">) =>
    apiClient.post<FaqItem>("/faq", body).then((r) => r.data),
  update: (id: string, body: Partial<Omit<FaqItem, "id">>) =>
    apiClient.patch<FaqItem>(`/faq/${id}`, body).then((r) => r.data),
  remove: (id: string) => apiClient.delete<void>(`/faq/${id}`).then((r) => r.data),
};

// ---------- Notifications ----------

export const notificationsApi = {
  log: (params: ListParams) =>
    apiClient
      .get<Paginated<NotificationLogEntry>>("/notifications/log", { params })
      .then((r) => r.data),
  getSettings: () =>
    apiClient
      .get<NotificationSettingEntry[]>("/notifications/settings")
      .then((r) => r.data),
  updateSettings: (event_key: string, body: Partial<Pick<NotificationSettingEntry, "telegram" | "email">>) =>
    apiClient
      .patch<NotificationSettingEntry>(`/notifications/settings/${event_key}`, body)
      .then((r) => r.data),
};

// ---------- System ----------

export const systemApi = {
  getSettings: () => apiClient.get<AppSettings>("/settings").then((r) => r.data),
  updateSettings: (body: Partial<AppSettings>) =>
    apiClient.patch<AppSettings>("/settings", body).then((r) => r.data),
  getTerms: () => apiClient.get<Terms>("/terms").then((r) => r.data),
  putTerms: (body: Terms) => apiClient.put<Terms>("/terms", body).then((r) => r.data),
  listAdmins: () => apiClient.get<AdminAccount[]>("/admins").then((r) => r.data),
  createAdmin: (body: AdminAccountInput) =>
    apiClient.post<AdminAccount>("/admins", body).then((r) => r.data),
  updateAdmin: (id: string, body: Partial<AdminAccountInput>) =>
    apiClient.patch<AdminAccount>(`/admins/${id}`, body).then((r) => r.data),
  audit: (params: ListParams) =>
    apiClient
      .get<Paginated<AuditLogEntry>>("/audit", { params })
      .then((r) => r.data),
};
