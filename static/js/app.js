/**
 * 编队识别规则管理系统 - Vue3前端应用
 */

const { createApp, ref, computed, onMounted, watch } = Vue;
const { createRouter, createWebHashHistory } = VueRouter;

// API基础URL
const API_BASE = '';

// ==================== 组件：规则预设列表 ====================

const PresetList = {
    template: `
    <div class="preset-list">
        <div class="page-header">
            <h2><i class="mdi mdi-folder-cog"></i> 规则预设管理</h2>
            <button class="btn btn-primary" @click="showCreateModal = true">
                <i class="mdi mdi-plus"></i> 新建预设
            </button>
        </div>

        <div class="filter-bar">
            <select v-model="filterCategory" class="form-select">
                <option value="">全部分类</option>
                <option value="system">系统预设</option>
                <option value="custom">自定义预设</option>
            </select>
            <input type="text" v-model="searchQuery" placeholder="搜索预设..." class="form-input">
        </div>

        <div class="preset-grid">
            <div v-for="preset in filteredPresets" :key="preset.id" 
                 class="preset-card" :class="{ 'system': preset.category === 'system' }">
                <div class="preset-header">
                    <h3>{{ preset.name }}</h3>
                    <span class="badge" :class="preset.category">{{ preset.category }}</span>
                </div>
                <p class="description">{{ preset.description || '无描述' }}</p>
                <div class="preset-stats">
                    <span><i class="mdi mdi-ruler"></i> {{ preset.rule_count }} 条规则</span>
                    <span v-if="preset.is_default" class="default-badge">默认</span>
                </div>
                <div class="preset-actions">
                    <button class="btn btn-sm" @click="viewPreset(preset)">
                        <i class="mdi mdi-eye"></i> 查看
                    </button>
                    <button class="btn btn-sm btn-primary" @click="editPreset(preset)">
                        <i class="mdi mdi-pencil"></i> 编辑
                    </button>
                    <button class="btn btn-sm btn-success" @click="applyPreset(preset)">
                        <i class="mdi mdi-check"></i> 应用
                    </button>
                    <button v-if="preset.category === 'custom'" 
                            class="btn btn-sm btn-danger" 
                            @click="deletePreset(preset)">
                        <i class="mdi mdi-delete"></i>
                    </button>
                </div>
            </div>
        </div>

        <!-- 创建预设模态框 -->
        <div v-if="showCreateModal" class="modal">
            <div class="modal-content">
                <h3>新建规则预设</h3>
                <div class="form-group">
                    <label>名称</label>
                    <input v-model="newPreset.name" class="form-input" placeholder="预设名称">
                </div>
                <div class="form-group">
                    <label>描述</label>
                    <textarea v-model="newPreset.description" class="form-input" 
                              placeholder="预设描述"></textarea>
                </div>
                <div class="modal-actions">
                    <button class="btn" @click="showCreateModal = false">取消</button>
                    <button class="btn btn-primary" @click="createPreset">创建</button>
                </div>
            </div>
        </div>
    </div>
    `,
    setup() {
        const presets = ref([]);
        const filterCategory = ref('');
        const searchQuery = ref('');
        const showCreateModal = ref(false);
        const newPreset = ref({ name: '', description: '' });

        const filteredPresets = computed(() => {
            return presets.value.filter(p => {
                const matchCategory = !filterCategory.value || p.category === filterCategory.value;
                const matchSearch = !searchQuery.value ||
                    p.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
                    (p.description && p.description.toLowerCase().includes(searchQuery.value.toLowerCase()));
                return matchCategory && matchSearch;
            });
        });

        const loadPresets = async () => {
            try {
                const response = await axios.get(`${API_BASE}/api/v1/rules/presets?include_rules=false`);
                presets.value = response.data.data.presets;
            } catch (error) {
                alert('加载预设失败: ' + error.message);
            }
        };

        const createPreset = async () => {
            try {
                await axios.post(`${API_BASE}/api/v1/rules/presets`, newPreset.value);
                showCreateModal.value = false;
                newPreset.value = { name: '', description: '' };
                loadPresets();
            } catch (error) {
                alert('创建失败: ' + error.response?.data?.message || error.message);
            }
        };

        const viewPreset = (preset) => {
            router.push(`/presets/${preset.id}`);
        };

        const editPreset = (preset) => {
            router.push(`/presets/${preset.id}/edit`);
        };

        const applyPreset = async (preset) => {
            try {
                await axios.post(`${API_BASE}/api/v1/rules/presets/${preset.id}/apply`);
                alert(`预设 "${preset.name}" 已应用`);
            } catch (error) {
                alert('应用失败: ' + error.message);
            }
        };

        const deletePreset = async (preset) => {
            if (!confirm(`确定要删除预设 "${preset.name}" 吗？`)) return;

            try {
                await axios.delete(`${API_BASE}/api/v1/rules/presets/${preset.id}`);
                loadPresets();
            } catch (error) {
                alert('删除失败: ' + error.message);
            }
        };

        onMounted(loadPresets);

        return {
            presets,
            filterCategory,
            searchQuery,
            filteredPresets,
            showCreateModal,
            newPreset,
            createPreset,
            viewPreset,
            editPreset,
            applyPreset,
            deletePreset
        };
    }
};

// ==================== 组件：规则预设详情 ====================

const PresetDetail = {
    template: `
    <div class="preset-detail">
        <div class="page-header">
            <button class="btn btn-text" @click="$router.back()">
                <i class="mdi mdi-arrow-left"></i> 返回
            </button>
            <h2>{{ preset.name }}</h2>
            <div class="header-actions">
                <button class="btn btn-primary" @click="showAddRule = true">
                    <i class="mdi mdi-plus"></i> 添加规则
                </button>
                <button class="btn btn-success" @click="applyPreset">
                    <i class="mdi mdi-check"></i> 应用预设
                </button>
            </div>
        </div>

        <div class="preset-info card">
            <div class="info-row">
                <label>描述:</label>
                <span>{{ preset.description || '无' }}</span>
            </div>
            <div class="info-row">
                <label>分类:</label>
                <span class="badge" :class="preset.category">{{ preset.category }}</span>
            </div>
            <div class="info-row">
                <label>规则数:</label>
                <span>{{ rules.length }}</span>
            </div>
        </div>

        <div class="rules-section">
            <h3>规则列表</h3>
            <div class="rule-list">
                <div v-for="(rule, index) in sortedRules" :key="rule.id" 
                     class="rule-item" :class="{ 'disabled': !rule.enabled }">
                    <div class="rule-order">{{ index + 1 }}</div>
                    <div class="rule-info">
                        <div class="rule-header">
                            <strong>{{ rule.name }}</strong>
                            <span class="rule-type">{{ rule.rule_type }}</span>
                            <span class="badge" :class="rule.priority">{{ rule.priority }}</span>
                            <span v-if="!rule.enabled" class="badge disabled">已禁用</span>
                        </div>
                        <div class="rule-params">
                            <code>{{ JSON.stringify(rule.params) }}</code>
                        </div>
                    </div>
                    <div class="rule-stats">
                        <div class="stat" title="评估次数">
                            <i class="mdi mdi-counter"></i> {{ rule.statistics?.evaluation_count || 0 }}
                        </div>
                        <div class="stat" title="通过率">
                            <i class="mdi mdi-percent"></i> 
                            {{ ((rule.statistics?.pass_rate || 0) * 100).toFixed(1) }}%
                        </div>
                    </div>
                    <div class="rule-actions">
                        <button class="btn btn-sm" @click="editRule(rule)">
                            <i class="mdi mdi-pencil"></i>
                        </button>
                        <button class="btn btn-sm" :class="rule.enabled ? 'btn-warning' : 'btn-success'"
                                @click="toggleRule(rule)">
                            <i class="mdi" :class="rule.enabled ? 'mdi-pause' : 'mdi-play'"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" @click="deleteRule(rule)">
                            <i class="mdi mdi-delete"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- 添加/编辑规则模态框 -->
        <div v-if="showAddRule || editingRule" class="modal">
            <div class="modal-content large">
                <h3>{{ editingRule ? '编辑规则' : '添加规则' }}</h3>
                
                <div class="form-row">
                    <div class="form-group">
                        <label>规则名称</label>
                        <input v-model="ruleForm.name" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>规则类型</label>
                        <select v-model="ruleForm.rule_type" class="form-select">
                            <option value="DistanceRule">距离规则</option>
                            <option value="AltitudeRule">高度规则</option>
                            <option value="SpeedRule">速度规则</option>
                            <option value="HeadingRule">航向规则</option>
                            <option value="AttributeRule">属性规则</option>
                            <option value="PlatformTypeRule">平台类型规则</option>
                        </select>
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label>优先级</label>
                        <select v-model="ruleForm.priority" class="form-select">
                            <option value="CRITICAL">关键</option>
                            <option value="HIGH">高</option>
                            <option value="MEDIUM">中</option>
                            <option value="LOW">低</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>权重</label>
                        <input type="number" v-model="ruleForm.weight" step="0.1" 
                               min="0" max="2" class="form-input">
                    </div>
                </div>

                <div class="form-group">
                    <label>规则参数 (JSON)</label>
                    <textarea v-model="ruleParamsJson" class="form-input code" rows="6"></textarea>
                </div>

                <div class="modal-actions">
                    <button class="btn" @click="closeRuleModal">取消</button>
                    <button class="btn btn-primary" @click="saveRule">保存</button>
                </div>
            </div>
        </div>
    </div>
    `,
    props: ['id'],
    setup(props) {
        const preset = ref({});
        const rules = ref([]);
        const showAddRule = ref(false);
        const editingRule = ref(null);

        const ruleForm = ref({
            name: '',
            rule_type: 'DistanceRule',
            priority: 'MEDIUM',
            weight: 1.0,
            params: {}
        });

        const ruleParamsJson = computed({
            get: () => JSON.stringify(ruleForm.value.params, null, 2),
            set: (val) => {
                try {
                    ruleForm.value.params = JSON.parse(val);
                } catch (e) {}
            }
        });

        const sortedRules = computed(() => {
            return [...rules.value].sort((a, b) => a.order - b.order);
        });

        const loadPreset = async () => {
            try {
                const response = await axios.get(`${API_BASE}/api/v1/rules/presets/${props.id}?include_rules=true`);
                preset.value = response.data.data;
                rules.value = response.data.data.rules || [];
            } catch (error) {
                alert('加载预设详情失败: ' + error.message);
            }
        };

        const applyPreset = async () => {
            try {
                await axios.post(`${API_BASE}/api/v1/rules/presets/${props.id}/apply`);
                alert('预设已应用');
            } catch (error) {
                alert('应用失败: ' + error.message);
            }
        };

        const saveRule = async () => {
            try {
                const data = {
                    ...ruleForm.value,
                    preset_id: props.id,
                    enabled: true
                };

                if (editingRule.value) {
                    await axios.put(`${API_BASE}/api/v1/rules/${editingRule.value.id}`, data);
                } else {
                    await axios.post(`${API_BASE}/api/v1/rules`, data);
                }

                closeRuleModal();
                loadPreset();
            } catch (error) {
                alert('保存失败: ' + error.message);
            }
        };

        const editRule = (rule) => {
            editingRule.value = rule;
            ruleForm.value = {
                name: rule.name,
                rule_type: rule.rule_type,
                priority: rule.priority,
                weight: rule.weight,
                params: { ...rule.params }
            };
        };

        const toggleRule = async (rule) => {
            try {
                const action = rule.enabled ? 'disable' : 'enable';
                await axios.post(`${API_BASE}/api/v1/rules/${rule.id}/${action}`);
                loadPreset();
            } catch (error) {
                alert('操作失败: ' + error.message);
            }
        };

        const deleteRule = async (rule) => {
            if (!confirm(`确定要删除规则 "${rule.name}" 吗？`)) return;

            try {
                await axios.delete(`${API_BASE}/api/v1/rules/${rule.id}`);
                loadPreset();
            } catch (error) {
                alert('删除失败: ' + error.message);
            }
        };

        const closeRuleModal = () => {
            showAddRule.value = false;
            editingRule.value = null;
            ruleForm.value = {
                name: '',
                rule_type: 'DistanceRule',
                priority: 'MEDIUM',
                weight: 1.0,
                params: {}
            };
        };

        onMounted(loadPreset);

        return {
            preset,
            rules,
            sortedRules,
            showAddRule,
            editingRule,
            ruleForm,
            ruleParamsJson,
            applyPreset,
            saveRule,
            editRule,
            toggleRule,
            deleteRule,
            closeRuleModal
        };
    }
};

// ==================== 组件：规则统计 ====================

const RuleStatistics = {
    template: `
    <div class="statistics-page">
        <h2><i class="mdi mdi-chart-bar"></i> 规则统计</h2>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{{ stats.overview?.total_presets || 0 }}</div>
                <div class="stat-label">预设总数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.overview?.total_rules || 0 }}</div>
                <div class="stat-label">规则总数</div>
            </div>
            <div class="stat-card success">
                <div class="stat-value">{{ stats.overview?.enabled_rules || 0 }}</div>
                <div class="stat-label">已启用</div>
            </div>
            <div class="stat-card warning">
                <div class="stat-value">{{ stats.overview?.disabled_rules || 0 }}</div>
                <div class="stat-label">已禁用</div>
            </div>
        </div>

        <div class="charts-section">
            <div class="chart-card">
                <h3>规则类型分布</h3>
                <div class="type-list">
                    <div v-for="(count, type) in stats.type_distribution" :key="type" 
                         class="type-item">
                        <span class="type-name">{{ type }}</span>
                        <div class="type-bar">
                            <div class="bar-fill" :style="{ width: getTypePercent(count) + '%' }"></div>
                        </div>
                        <span class="type-count">{{ count }}</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="recent-changes">
            <h3>最近修改</h3>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>时间</th>
                        <th>操作</th>
                        <th>规则</th>
                        <th>操作人</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="change in stats.recent_changes" :key="change.id">
                        <td>{{ formatTime(change.performed_at) }}</td>
                        <td>
                            <span class="badge" :class="change.action">{{ change.action }}</span>
                        </td>
                        <td>{{ change.rule_id }}</td>
                        <td>{{ change.performed_by }}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    `,
    setup() {
        const stats = ref({});

        const loadStats = async () => {
            try {
                const response = await axios.get(`${API_BASE}/api/v1/rules/statistics`);
                stats.value = response.data.data;
            } catch (error) {
                console.error('加载统计失败:', error);
            }
        };

        const getTypePercent = (count) => {
            const total = Object.values(stats.value.type_distribution || {}).reduce((a, b) => a + b, 0);
            return total > 0 ? (count / total) * 100 : 0;
        };

        const formatTime = (timeStr) => {
            if (!timeStr) return '-';
            const date = new Date(timeStr);
            return date.toLocaleString('zh-CN');
        };

        onMounted(loadStats);

        return {
            stats,
            getTypePercent,
            formatTime
        };
    }
};

// ==================== 路由配置 ====================

const routes = [
    { path: '/', redirect: '/presets' },
    { path: '/presets', component: PresetList },
    { path: '/presets/:id', component: PresetDetail, props: true },
    { path: '/presets/:id/edit', component: PresetDetail, props: true },
    { path: '/statistics', component: RuleStatistics }
];

const router = createRouter({
    history: createWebHashHistory(),
    routes
});

// ==================== 主应用 ====================

const App = {
    template: `
    <div class="app">
        <header class="app-header">
            <div class="logo">
                <i class="mdi mdi-airplane-marker"></i>
                <span>编队识别规则管理系统</span>
            </div>
            <nav class="nav-menu">
                <router-link to="/presets" class="nav-item">
                    <i class="mdi mdi-folder-cog"></i> 预设管理
                </router-link>
                <router-link to="/statistics" class="nav-item">
                    <i class="mdi mdi-chart-bar"></i> 统计
                </router-link>
                <a href="/docs" target="_blank" class="nav-item">
                    <i class="mdi mdi-book-open"></i> API文档
                </a>
            </nav>
        </header>
        
        <main class="app-main">
            <router-view></router-view>
        </main>
    </div>
    `
};

// 创建并挂载应用
const app = createApp(App);
app.use(router);
app.mount('#app');