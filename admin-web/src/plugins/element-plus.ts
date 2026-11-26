import type { App, Component } from 'vue'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElBreadcrumb, ElBreadcrumbItem } from 'element-plus/es/components/breadcrumb/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElCheckbox, ElCheckboxGroup } from 'element-plus/es/components/checkbox/index'
import { ElCol } from 'element-plus/es/components/col/index'
import { ElConfigProvider } from 'element-plus/es/components/config-provider/index'
import { ElAside, ElContainer, ElHeader, ElMain } from 'element-plus/es/components/container/index'
import { ElDescriptions, ElDescriptionsItem } from 'element-plus/es/components/descriptions/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDrawer } from 'element-plus/es/components/drawer/index'
import {
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
} from 'element-plus/es/components/dropdown/index'
import { ElEmpty } from 'element-plus/es/components/empty/index'
import {
  ElForm,
  ElFormItem,
  type FormInstance,
  type FormRules,
} from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElLoading } from 'element-plus/es/components/loading/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { ElPagination } from 'element-plus/es/components/pagination/index'
import { ElRadioButton, ElRadioGroup } from 'element-plus/es/components/radio/index'
import { ElRow } from 'element-plus/es/components/row/index'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index'
import { ElSlider } from 'element-plus/es/components/slider/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElTabPane, ElTabs } from 'element-plus/es/components/tabs/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElTooltip } from 'element-plus/es/components/tooltip/index'
import {
  ArrowDown,
  ChatDotRound,
  Check,
  Close,
  Collection,
  Cpu,
  Delete,
  Document,
  Download,
  EditPen,
  Expand,
  Files,
  Fold,
  FolderOpened,
  Key,
  Lock,
  MagicStick,
  Message,
  Monitor,
  Odometer,
  Plus,
  Postcard,
  Reading,
  Refresh,
  Right,
  Search,
  Setting,
  Upload,
  User,
  UserFilled,
} from '@element-plus/icons-vue'

// 仅按需加载实际使用到的 Element Plus 基础与组件样式（避免全量引入未用组件与 CSS）
import 'element-plus/es/components/base/style/css'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/aside/style/css'
import 'element-plus/es/components/breadcrumb/style/css'
import 'element-plus/es/components/breadcrumb-item/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/checkbox-group/style/css'
import 'element-plus/es/components/col/style/css'
import 'element-plus/es/components/config-provider/style/css'
import 'element-plus/es/components/container/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/descriptions-item/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/drawer/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/header/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/loading/style/css'
import 'element-plus/es/components/main/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/overlay/style/css'
import 'element-plus/es/components/pagination/style/css'
import 'element-plus/es/components/popper/style/css'
import 'element-plus/es/components/radio/style/css'
import 'element-plus/es/components/radio-button/style/css'
import 'element-plus/es/components/radio-group/style/css'
import 'element-plus/es/components/row/style/css'
import 'element-plus/es/components/scrollbar/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/slider/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'

export { ElMessage, ElMessageBox, type FormInstance, type FormRules }

const COMPONENTS: Component[] = [
  ElAlert,
  ElAside,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElCol,
  ElConfigProvider,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMain,
  ElOption,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
]

const ICONS: Record<string, Component> = {
  ArrowDown,
  ChatDotRound,
  Check,
  Close,
  Collection,
  Cpu,
  Delete,
  Document,
  Download,
  EditPen,
  Expand,
  Files,
  Fold,
  FolderOpened,
  Key,
  Lock,
  MagicStick,
  Message,
  Monitor,
  Odometer,
  Plus,
  Postcard,
  Reading,
  Refresh,
  Right,
  Search,
  Setting,
  Upload,
  User,
  UserFilled,
}

export function setupElementPlus(app: App): void {
  for (const comp of COMPONENTS) {
    if (comp.name) {
      app.component(comp.name, comp)
    }
  }
  app.use(ElLoading)
  for (const [name, icon] of Object.entries(ICONS)) {
    app.component(name, icon)
  }
}
