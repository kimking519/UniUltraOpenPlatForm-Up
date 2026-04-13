/**
 * 表格列拖拽功能 - 重构版
 * 使用列唯一标识而非列名，避免张冠李戴
 */

class ColumnDragger {
    constructor(tableId, storageKey) {
        this.table = document.getElementById(tableId);
        this.storageKey = storageKey;
        if (!this.table) return;

        this.init();
    }

    init() {
        const headerRow = this.table.querySelector('thead tr');
        if (!headerRow) return;

        // 给每个th分配唯一标识
        const ths = headerRow.querySelectorAll('th');
        ths.forEach((th, index) => {
            // 使用现有data-field或生成唯一ID
            const existingId = th.getAttribute('data-field') || th.getAttribute('data-col-id');
            if (!existingId) {
                th.setAttribute('data-col-id', `col_${index}`);
            }

            // checkbox列和操作列不可拖拽
            if (th.querySelector('input[type="checkbox"]') || th.style.position === 'sticky') {
                th.setAttribute('data-draggable', 'false');
                return;
            }

            th.setAttribute('draggable', 'true');
            th.style.cursor = 'grab';

            th.addEventListener('dragstart', this.onDragStart.bind(this));
            th.addEventListener('dragover', this.onDragOver.bind(this));
            th.addEventListener('drop', this.onDrop.bind(this));
            th.addEventListener('dragend', this.onDragEnd.bind(this));
        });

        // 恢复保存的列顺序
        this.restoreColumnOrder();
    }

    onDragStart(e) {
        const th = e.target.closest('th');
        if (!th || th.getAttribute('draggable') !== 'true') return;

        this.draggedTh = th;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', th.getAttribute('data-col-id'));

        setTimeout(() => {
            th.style.opacity = '0.5';
            th.style.backgroundColor = '#e0f2fe';
        }, 0);
    }

    onDragOver(e) {
        e.preventDefault();
        const th = e.target.closest('th');
        if (!th || th.getAttribute('draggable') !== 'true' || th === this.draggedTh) return;
        th.style.borderLeft = '3px solid #3b82f6';
    }

    onDrop(e) {
        e.preventDefault();
        const targetTh = e.target.closest('th');
        if (!targetTh || targetTh.getAttribute('draggable') !== 'true' || targetTh === this.draggedTh) return;

        targetTh.style.borderLeft = '';

        // 获取两列的唯一标识
        const fromId = this.draggedTh.getAttribute('data-col-id');
        const toId = targetTh.getAttribute('data-col-id');

        // 交换列
        this.swapColumnsById(fromId, toId);
        this.saveColumnOrder();
    }

    onDragEnd(e) {
        if (this.draggedTh) {
            this.draggedTh.style.opacity = '1';
            this.draggedTh.style.backgroundColor = '';
        }
        this.table.querySelectorAll('thead th').forEach(th => th.style.borderLeft = '');
        this.draggedTh = null;
    }

    swapColumnsById(fromId, toId) {
        const headerRow = this.table.querySelector('thead tr');
        const tbody = this.table.querySelector('tbody');

        // 找到两列在当前DOM中的实际位置索引
        const ths = Array.from(headerRow.querySelectorAll('th'));
        const fromIndex = ths.findIndex(th => th.getAttribute('data-col-id') === fromId);
        const toIndex = ths.findIndex(th => th.getAttribute('data-col-id') === toId);

        if (fromIndex === -1 || toIndex === -1) return;

        // 交换表头
        const fromTh = ths[fromIndex];
        const toTh = ths[toIndex];

        // 使用insertBefore实现交换
        if (fromIndex < toIndex) {
            toTh.parentNode.insertBefore(fromTh, toTh.nextSibling);
        } else {
            toTh.parentNode.insertBefore(fromTh, toTh);
        }

        // 交换表体每行的对应单元格
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const cells = Array.from(row.querySelectorAll('td'));
            const fromCell = cells[fromIndex];
            const toCell = cells[toIndex];

            if (fromCell && toCell) {
                if (fromIndex < toIndex) {
                    toCell.parentNode.insertBefore(fromCell, toCell.nextSibling);
                } else {
                    toCell.parentNode.insertBefore(fromCell, toCell);
                }
            }
        });
    }

    saveColumnOrder() {
        const headerRow = this.table.querySelector('thead tr');
        const ths = headerRow.querySelectorAll('th');
        // 只保存可拖拽列的顺序（用唯一ID标识）
        const order = Array.from(ths)
            .filter(th => th.getAttribute('draggable') === 'true')
            .map(th => th.getAttribute('data-col-id'));
        localStorage.setItem(this.storageKey, JSON.stringify(order));
    }

    restoreColumnOrder() {
        const savedOrder = localStorage.getItem(this.storageKey);
        if (!savedOrder) return;

        try {
            const savedIds = JSON.parse(savedOrder);
            const headerRow = this.table.querySelector('thead tr');
            const tbody = this.table.querySelector('tbody');
            const currentThs = Array.from(headerRow.querySelectorAll('th'));

            // 获取当前可拖拽列的ID和索引
            const currentDraggable = currentThs
                .filter(th => th.getAttribute('draggable') === 'true')
                .map(th => ({ id: th.getAttribute('data-col-id'), th }));

            // 检查数量是否匹配
            if (savedIds.length !== currentDraggable.length) {
                localStorage.removeItem(this.storageKey);
                return;
            }

            // 检查所有保存的ID是否都存在
            const allIdsExist = savedIds.every(id => currentDraggable.some(d => d.id === id));
            if (!allIdsExist) {
                localStorage.removeItem(this.storageKey);
                return;
            }

            // 按保存的顺序重新排列
            savedIds.forEach((targetId, newPos) => {
                // 找到当前这个ID在哪
                const currentPos = currentDraggable.findIndex(d => d.id === targetId);

                if (currentPos !== newPos) {
                    // 需要移动
                    const fromTh = currentDraggable[currentPos].th;
                    const toTh = currentDraggable[newPos].th;

                    // 获取实际DOM索引
                    const fromDomIndex = currentThs.indexOf(fromTh);
                    const toDomIndex = currentThs.indexOf(toTh);

                    // 交换表头
                    if (fromDomIndex < toDomIndex) {
                        toTh.parentNode.insertBefore(fromTh, toTh.nextSibling);
                    } else {
                        toTh.parentNode.insertBefore(fromTh, toTh);
                    }

                    // 交换表体
                    const rows = tbody.querySelectorAll('tr');
                    rows.forEach(row => {
                        const cells = Array.from(row.querySelectorAll('td'));
                        const fromCell = cells[fromDomIndex];
                        const toCell = cells[toDomIndex];

                        if (fromCell && toCell) {
                            if (fromDomIndex < toDomIndex) {
                                toCell.parentNode.insertBefore(fromCell, toCell.nextSibling);
                            } else {
                                toCell.parentNode.insertBefore(fromCell, toCell);
                            }
                        }
                    });

                    // 更新currentThs数组（交换元素）
                    currentThs[fromDomIndex] = fromTh;
                    currentThs[toDomIndex] = toTh;
                }
            });

        } catch (e) {
            console.error('恢复列顺序失败:', e);
            localStorage.removeItem(this.storageKey);
        }
    }
}

function initColumnDragger(tableId, storageKey) {
    return new ColumnDragger(tableId, storageKey);
}