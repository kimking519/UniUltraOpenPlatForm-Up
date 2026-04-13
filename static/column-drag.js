/**
 * 表格列拖拽功能
 * 支持自由调整列顺序，顺序保存到 localStorage
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

        // 获取所有可拖拽的列（排除checkbox列和sticky操作列）
        const ths = headerRow.querySelectorAll('th');
        ths.forEach((th, index) => {
            // checkbox列和操作列不可拖拽
            if (th.querySelector('input[type="checkbox"]') ||
                th.style.position === 'sticky') {
                th.setAttribute('data-draggable', 'false');
                return;
            }

            th.setAttribute('draggable', 'true');
            th.setAttribute('data-col-index', index);
            th.style.cursor = 'grab';

            // 添加拖拽事件
            th.addEventListener('dragstart', this.onDragStart.bind(this));
            th.addEventListener('dragover', this.onDragOver.bind(this));
            th.addEventListener('drop', this.onDrop.bind(this));
            th.addEventListener('dragend', this.onDragEnd.bind(this));

            // 添加拖拽提示样式
            th.addEventListener('mouseenter', () => {
                if (th.getAttribute('draggable') === 'true') {
                    th.style.backgroundColor = 'var(--primary-light, #e0f2fe)';
                }
            });
            th.addEventListener('mouseleave', () => {
                th.style.backgroundColor = '';
            });
        });

        // 恢复保存的列顺序
        this.restoreColumnOrder();
    }

    onDragStart(e) {
        const th = e.target.closest('th');
        if (th.getAttribute('draggable') !== 'true') return;

        this.draggedCol = parseInt(th.getAttribute('data-col-index'));
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', this.draggedCol);

        // 添加拖拽样式
        setTimeout(() => {
            th.style.opacity = '0.5';
            th.style.backgroundColor = 'var(--primary, #3b82f6)';
        }, 0);
    }

    onDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        const th = e.target.closest('th');
        if (!th || th.getAttribute('draggable') !== 'true') return;

        const targetCol = parseInt(th.getAttribute('data-col-index'));
        if (targetCol !== this.draggedCol) {
            th.style.borderLeft = '3px solid var(--primary, #3b82f6)';
        }
    }

    onDrop(e) {
        e.preventDefault();

        const th = e.target.closest('th');
        if (!th || th.getAttribute('draggable') !== 'true') return;

        const targetCol = parseInt(th.getAttribute('data-col-index'));
        if (targetCol === this.draggedCol) return;

        // 清除边框样式
        th.style.borderLeft = '';

        // 执行列交换
        this.swapColumns(this.draggedCol, targetCol);

        // 保存列顺序
        this.saveColumnOrder();
    }

    onDragEnd(e) {
        const th = e.target.closest('th');
        if (!th) return;

        // 清除拖拽样式
        th.style.opacity = '1';
        th.style.backgroundColor = '';

        // 清除所有边框提示
        const allThs = this.table.querySelectorAll('thead th');
        allThs.forEach(t => t.style.borderLeft = '');

        this.draggedCol = null;
    }

    swapColumns(fromIndex, toIndex) {
        const headerRow = this.table.querySelector('thead tr');
        const tbody = this.table.querySelector('tbody');
        const ths = Array.from(headerRow.querySelectorAll('th'));

        // 获取可拖拽列的实际索引（排除不可拖拽的列）
        const draggableThs = ths.filter(th => th.getAttribute('data-draggable') !== 'false');

        // 在可拖拽列中找到from和to的位置
        let fromDraggableIndex = -1;
        let toDraggableIndex = -1;
        let count = 0;

        ths.forEach((th, i) => {
            if (th.getAttribute('data-draggable') !== 'false') {
                if (i === fromIndex) fromDraggableIndex = count;
                if (i === toIndex) toDraggableIndex = count;
                count++;
            }
        });

        if (fromDraggableIndex === -1 || toDraggableIndex === -1) return;

        // 获取两个列元素
        const fromTh = draggableThs[fromDraggableIndex];
        const toTh = draggableThs[toDraggableIndex];

        // 交换表头
        const fromRect = fromTh.getBoundingClientRect();
        const toRect = toTh.getBoundingClientRect();

        if (fromDraggableIndex < toDraggableIndex) {
            toTh.parentNode.insertBefore(fromTh, toTh.nextSibling);
        } else {
            toTh.parentNode.insertBefore(fromTh, toTh);
        }

        // 交换表体每行的对应单元格
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const cells = Array.from(row.querySelectorAll('td'));
            const draggableCells = cells.filter((td, i) => {
                // 对应th的可拖拽属性
                return ths[i]?.getAttribute('data-draggable') !== 'false';
            });

            if (draggableCells.length > 0) {
                const fromCell = draggableCells[fromDraggableIndex];
                const toCell = draggableCells[toDraggableIndex];

                if (fromDraggableIndex < toDraggableIndex) {
                    toCell.parentNode.insertBefore(fromCell, toCell.nextSibling);
                } else {
                    toCell.parentNode.insertBefore(fromCell, toCell);
                }
            }
        });

        // 更新data-col-index
        this.updateColIndexes();
    }

    updateColIndexes() {
        const headerRow = this.table.querySelector('thead tr');
        const ths = headerRow.querySelectorAll('th');
        ths.forEach((th, i) => {
            th.setAttribute('data-col-index', i);
        });
    }

    saveColumnOrder() {
        const headerRow = this.table.querySelector('thead tr');
        const ths = headerRow.querySelectorAll('th');
        const order = Array.from(ths).map(th => th.textContent.trim().substring(0, 20));
        localStorage.setItem(this.storageKey, JSON.stringify(order));
    }

    restoreColumnOrder() {
        const savedOrder = localStorage.getItem(this.storageKey);
        if (!savedOrder) return;

        try {
            const order = JSON.parse(savedOrder);
            const headerRow = this.table.querySelector('thead tr');
            const ths = Array.from(headerRow.querySelectorAll('th'));
            const tbody = this.table.querySelector('tbody');

            // 创建映射：列名 -> 当前索引
            const currentOrder = ths.map(th => th.textContent.trim().substring(0, 20));

            // 只对可拖拽列进行排序
            const draggableIndices = ths
                .map((th, i) => ({ th, index: i, draggable: th.getAttribute('data-draggable') !== 'false' }))
                .filter(item => item.draggable);

            // 计算新顺序
            const newDraggableOrder = order.filter(name =>
                draggableIndices.some(item => item.th.textContent.trim().substring(0, 20) === name)
            );

            // 如果保存的列数与当前不一致，不恢复
            if (newDraggableOrder.length !== draggableIndices.length) {
                localStorage.removeItem(this.storageKey);
                return;
            }

            // 重新排列可拖拽列
            let draggedCount = 0;
            newDraggableOrder.forEach((targetName, newPos) => {
                const currentPos = draggableIndices.findIndex(item =>
                    item.th.textContent.trim().substring(0, 20) === targetName
                );

                if (currentPos !== -1 && currentPos !== newPos) {
                    // 找到当前位置的th和目标位置的th
                    const fromTh = draggableIndices[currentPos].th;
                    const toTh = draggableIndices[newPos].th;

                    // 交换表头
                    if (currentPos < newPos) {
                        toTh.parentNode.insertBefore(fromTh, toTh.nextSibling);
                    } else {
                        toTh.parentNode.insertBefore(fromTh, toTh);
                    }

                    // 交换表体
                    const rows = tbody.querySelectorAll('tr');
                    rows.forEach(row => {
                        const cells = Array.from(row.querySelectorAll('td'));
                        const draggableCells = draggableIndices.map(item => cells[item.index]);

                        if (draggableCells.length > 0) {
                            const fromCell = draggableCells[currentPos];
                            const toCell = draggableCells[newPos];

                            if (currentPos < newPos) {
                                toCell.parentNode.insertBefore(fromCell, toCell.nextSibling);
                            } else {
                                toCell.parentNode.insertBefore(fromCell, toCell);
                            }
                        }
                    });

                    // 更新draggableIndices引用
                    draggableIndices[currentPos].th = fromTh;
                    draggableIndices[newPos].th = toTh;
                }
            });

            this.updateColIndexes();
        } catch (e) {
            console.error('恢复列顺序失败:', e);
            localStorage.removeItem(this.storageKey);
        }
    }
}

// 导出工厂函数
function initColumnDragger(tableId, storageKey) {
    return new ColumnDragger(tableId, storageKey);
}