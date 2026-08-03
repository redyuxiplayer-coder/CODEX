from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from wr_barcode.core import (
    BarcodeLine,
    generate_barcode_pdf,
    generate_barcode_pdf_for_lines,
    generate_barcode_pdf_from_excel,
    list_contracts_from_excel,
    read_contract_quantity_grid,
    read_unshipped_quantity_grid_from_excel,
)


DEFAULT_SOURCE = Path(r"C:\Users\Administrator\Desktop\老板娘文件\WZY-TS03条形码.pdf")
DEFAULT_EXCEL = Path(r"C:\Users\Administrator\Desktop\老板娘文件\WR全部合同订单发货整合表.xlsx")
DEFAULT_OUTPUT_DIR = Path(r"E:\CODEX\1-项目\仓库系统管理\订单报表系统\output\wr_barcode")
DEFAULT_TABLE = """颜色 尺码 XS S M L XL 2XL
黑色 50 150 360 370 300 80
"""


class BarcodeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("WR老板娘条码打印生成器")
        self.geometry("920x680")
        self.minsize(840, 600)

        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE) if DEFAULT_SOURCE.exists() else "")
        self.excel_var = tk.StringVar(value=str(DEFAULT_EXCEL) if DEFAULT_EXCEL.exists() else "")
        self.contract_var = tk.StringVar(value="")
        self.extra_var = tk.StringVar(value="0")
        self.status_var = tk.StringVar(value="选择条码 PDF 和 WR 总表/合同，读取后生成。")
        self.contracts: list[str] = []
        self.quantity_sizes: list[str] = []
        self.quantity_rows: dict[str, dict[str, object]] = {}
        self.quantity_editor: tk.Entry | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(4, weight=1)

        ttk.Label(root, text="源条码 PDF").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(root, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 10))
        ttk.Button(root, text="选择", command=self._choose_pdf).grid(row=0, column=2, pady=(0, 10))

        ttk.Label(root, text="WR总表/合同").grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(root, textvariable=self.excel_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 10))
        excel_actions = ttk.Frame(root)
        excel_actions.grid(row=1, column=2, sticky="ew", pady=(0, 10))
        ttk.Button(excel_actions, text="选择", command=self._choose_excel).pack(side="left")
        ttk.Button(excel_actions, text="读取", command=self._load_excel).pack(side="left", padx=(6, 0))

        ttk.Label(root, text="未发货合同").grid(row=2, column=0, sticky="w", pady=(0, 10))
        self.contract_combo = ttk.Combobox(root, textvariable=self.contract_var, state="readonly")
        self.contract_combo.grid(row=2, column=1, columnspan=2, sticky="ew", padx=8, pady=(0, 10))
        self.contract_combo.bind("<<ComboboxSelected>>", self._on_contract_selected)

        ttk.Label(root, text="每个尺码额外加").grid(row=3, column=0, sticky="w", pady=(0, 10))
        extra_row = ttk.Frame(root)
        extra_row.grid(row=3, column=1, sticky="w", padx=8, pady=(0, 10))
        ttk.Spinbox(extra_row, from_=0, to=999, textvariable=self.extra_var, width=8).pack(side="left")
        ttk.Label(extra_row, text="张").pack(side="left", padx=(6, 0))

        notebook = ttk.Notebook(root)
        notebook.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(0, 10))

        contract_tab = ttk.Frame(notebook, padding=(0, 8, 0, 0))
        contract_tab.rowconfigure(0, weight=1)
        contract_tab.columnconfigure(0, weight=1)
        notebook.add(contract_tab, text="合同颜色数量")

        self.quantity_tree = ttk.Treeview(contract_tab, show="headings", selectmode="browse")
        quantity_y = ttk.Scrollbar(contract_tab, orient="vertical", command=self.quantity_tree.yview)
        quantity_x = ttk.Scrollbar(contract_tab, orient="horizontal", command=self.quantity_tree.xview)
        self.quantity_tree.configure(yscrollcommand=quantity_y.set, xscrollcommand=quantity_x.set)
        self.quantity_tree.grid(row=0, column=0, sticky="nsew")
        quantity_y.grid(row=0, column=1, sticky="ns")
        quantity_x.grid(row=1, column=0, sticky="ew")
        self.quantity_tree.bind("<ButtonRelease-1>", self._on_quantity_click)
        self._configure_quantity_tree(["XS", "S", "M", "L", "XL", "2XL"])

        manual_tab = ttk.Frame(notebook, padding=(0, 8, 0, 0))
        manual_tab.rowconfigure(0, weight=1)
        manual_tab.columnconfigure(0, weight=1)
        notebook.add(manual_tab, text="手动数量表")

        self.table_text = tk.Text(manual_tab, wrap="none", undo=True)
        manual_y = ttk.Scrollbar(manual_tab, orient="vertical", command=self.table_text.yview)
        manual_x = ttk.Scrollbar(manual_tab, orient="horizontal", command=self.table_text.xview)
        self.table_text.configure(yscrollcommand=manual_y.set, xscrollcommand=manual_x.set)
        self.table_text.grid(row=0, column=0, sticky="nsew")
        manual_y.grid(row=0, column=1, sticky="ns")
        manual_x.grid(row=1, column=0, sticky="ew")
        self.table_text.insert("1.0", DEFAULT_TABLE)

        actions = ttk.Frame(root)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Button(actions, text="按勾选颜色生成 PDF", command=self._generate_from_checked_rows).pack(side="left")
        ttk.Button(actions, text="按总表未发生成 PDF", command=self._generate_from_excel).pack(side="left", padx=8)
        ttk.Button(actions, text="按手动表格生成 PDF", command=self._generate_manual).pack(side="left")
        ttk.Button(actions, text="清空表格", command=self._clear_tables).pack(side="left", padx=8)
        ttk.Button(actions, text="打开生成文件夹", command=self._open_output_folder).pack(side="left")
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=12)

        if DEFAULT_EXCEL.exists():
            self.after(200, self._load_excel)

    def _choose_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择源条码 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if path:
            self.source_var.set(path)

    def _choose_excel(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 WR 总表或单个合同",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")],
        )
        if path:
            self.excel_var.set(path)
            self._load_excel()

    def _load_excel(self) -> None:
        path = Path(self.excel_var.get().strip())
        try:
            self._load_contracts(path)
            return
        except Exception:
            pass

        try:
            self._load_contract_quantity_grid(path)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            self.status_var.set("读取失败，请检查文件。")

    def _load_contracts(self, path: Path) -> None:
        self.contracts = list_contracts_from_excel(path)
        self._clear_quantity_table()
        self.contract_combo.configure(values=self.contracts)
        if self.contracts:
            self.contract_var.set(self.contracts[0])
            self._load_selected_total_contract_grid(show_errors=False)
            self.status_var.set(f"已读取 {len(self.contracts)} 个未发货合同，并显示当前合同颜色数量。")
        else:
            self.contract_var.set("")
            self.status_var.set("总表里没有未发货合同。")

    def _on_contract_selected(self, _event: tk.Event | None = None) -> None:
        self._load_selected_total_contract_grid(show_errors=True)

    def _load_selected_total_contract_grid(self, show_errors: bool) -> None:
        selected = self.contract_var.get().strip()
        if not selected:
            return
        contract_no = selected.split("|", 1)[0].strip()
        try:
            grid = read_unshipped_quantity_grid_from_excel(Path(self.excel_var.get().strip()), contract_no)
        except Exception as exc:
            if show_errors:
                messagebox.showerror("读取失败", str(exc))
            self.status_var.set("读取合同颜色数量失败。")
            return
        self._fill_quantity_grid(grid)
        self.status_var.set(f"已显示 {contract_no} 的 {len(grid.rows)} 个未发货颜色。单击数量可修改。")

    def _load_contract_quantity_grid(self, path: Path) -> None:
        grid = read_contract_quantity_grid(path)
        self.contracts = []
        self.contract_combo.configure(values=[])
        self.contract_var.set("")
        self._fill_quantity_grid(grid)
        self.status_var.set(f"已识别 {len(grid.rows)} 个颜色。单击打印列切换，单击数量可修改。")

    def _fill_quantity_grid(self, grid) -> None:
        self._clear_quantity_table()
        self._configure_quantity_tree(grid.sizes)
        for row in grid.rows:
            values = ["☑", row.color_label]
            values.extend(row.quantities.get(size, 0) for size in self.quantity_sizes)
            values.append(row.total)
            item_id = self.quantity_tree.insert("", "end", values=values)
            self.quantity_rows[item_id] = {
                "checked": True,
                "color": row.color_label,
                "quantities": dict(row.quantities),
            }

    def _configure_quantity_tree(self, sizes: list[str]) -> None:
        self.quantity_sizes = sizes
        columns = ["checked", "color", *sizes, "total"]
        self.quantity_tree.configure(columns=columns)
        headings = {"checked": "打印", "color": "颜色", "total": "合计"}
        for column in columns:
            self.quantity_tree.heading(column, text=headings.get(column, column))
            width = 56 if column not in {"color", "total"} else 110
            if column == "checked":
                width = 52
            self.quantity_tree.column(column, width=width, minwidth=44, anchor="center", stretch=column == "color")

    def _clear_tables(self) -> None:
        self._clear_quantity_table()
        self.table_text.delete("1.0", "end")

    def _open_output_folder(self) -> None:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DEFAULT_OUTPUT_DIR)
        self.status_var.set(f"已打开生成文件夹：{DEFAULT_OUTPUT_DIR}")

    def _clear_quantity_table(self) -> None:
        if self.quantity_editor is not None:
            self.quantity_editor.destroy()
            self.quantity_editor = None
        for item_id in self.quantity_tree.get_children():
            self.quantity_tree.delete(item_id)
        self.quantity_rows = {}

    def _on_quantity_click(self, event: tk.Event) -> None:
        item_id = self.quantity_tree.identify_row(event.y)
        column_id = self.quantity_tree.identify_column(event.x)
        if not item_id or not column_id:
            return
        column_index = int(column_id[1:]) - 1
        columns = list(self.quantity_tree["columns"])
        if column_index < 0 or column_index >= len(columns):
            return
        column_name = columns[column_index]
        if column_name == "checked":
            self._toggle_checked_row(item_id)
            return
        if column_name in self.quantity_sizes:
            self._edit_quantity_cell(item_id, column_name)

    def _toggle_checked_row(self, item_id: str) -> None:
        row = self.quantity_rows[item_id]
        row["checked"] = not bool(row["checked"])
        self._refresh_quantity_row(item_id)

    def _edit_quantity_cell(self, item_id: str, size: str) -> None:
        if self.quantity_editor is not None:
            self.quantity_editor.destroy()
        column_id = f"#{list(self.quantity_tree['columns']).index(size) + 1}"
        bbox = self.quantity_tree.bbox(item_id, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        quantities = self.quantity_rows[item_id]["quantities"]
        current = str(quantities.get(size, 0))
        editor = ttk.Entry(self.quantity_tree)
        editor.insert(0, current)
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        self.quantity_editor = editor

        def commit(_event: tk.Event | None = None) -> None:
            try:
                value = int(editor.get().strip() or "0")
                if value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("数量不对", "数量必须是 0 或正整数")
                return
            quantities[size] = value
            self._refresh_quantity_row(item_id)
            editor.destroy()
            self.quantity_editor = None

        editor.bind("<Return>", commit)
        editor.bind("<FocusOut>", commit)
        editor.bind("<Escape>", lambda _event: self._cancel_quantity_edit(editor))

    def _cancel_quantity_edit(self, editor: tk.Entry) -> None:
        editor.destroy()
        self.quantity_editor = None

    def _refresh_quantity_row(self, item_id: str) -> None:
        row = self.quantity_rows[item_id]
        quantities = row["quantities"]
        total = sum(int(quantities.get(size, 0)) for size in self.quantity_sizes)
        values = ["☑" if row["checked"] else "☐", row["color"]]
        values.extend(int(quantities.get(size, 0)) for size in self.quantity_sizes)
        values.append(total)
        self.quantity_tree.item(item_id, values=values)

    def _generate_manual(self) -> None:
        try:
            extra = int(self.extra_var.get().strip() or "0")
            table = self.table_text.get("1.0", "end")
            source = Path(self.source_var.get().strip())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output = DEFAULT_OUTPUT_DIR / f"WR老板娘条码打印_{timestamp}.pdf"
            result = generate_barcode_pdf(source, table, output, extra)
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
            self.status_var.set("生成失败，请检查提示。")
            return

        self.status_var.set(f"已生成 {result.total_pages} 张")
        messagebox.showinfo(
            "生成完成",
            f"打印 PDF：\n{result.output_pdf}\n\n数量明细：\n{result.manifest_path}\n\n合计：{result.total_pages} 张",
        )

    def _generate_from_checked_rows(self) -> None:
        try:
            lines: list[BarcodeLine] = []
            extra = int(self.extra_var.get().strip() or "0")
            for row in self.quantity_rows.values():
                if not row["checked"]:
                    continue
                color = str(row["color"])
                quantities = row["quantities"]
                for size in self.quantity_sizes:
                    quantity = int(quantities.get(size, 0))
                    if quantity > 0:
                        lines.append(BarcodeLine(color_label=color, color_code="", size=size, quantity=quantity + extra))
            if not lines:
                raise ValueError("请至少勾选一个有数量的颜色")
            source = Path(self.source_var.get().strip())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output = DEFAULT_OUTPUT_DIR / f"WR老板娘勾选颜色条码_{timestamp}.pdf"
            result = generate_barcode_pdf_for_lines(source, lines, output)
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
            self.status_var.set("生成失败，请检查提示。")
            return

        self.status_var.set(f"已按勾选颜色生成 {result.total_pages} 张")
        messagebox.showinfo(
            "生成完成",
            f"打印 PDF：\n{result.output_pdf}\n\n数量明细：\n{result.manifest_path}\n\n合计：{result.total_pages} 张",
        )

    def _generate_from_excel(self) -> None:
        try:
            selected = self.contract_var.get().strip()
            if not selected:
                raise ValueError("请先读取并选择一个未发货合同")
            contract_no = selected.split("|", 1)[0].strip()
            extra = int(self.extra_var.get().strip() or "0")
            source = Path(self.source_var.get().strip())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_contract = contract_no.replace("/", "-").replace("\\", "-")
            output = DEFAULT_OUTPUT_DIR / f"WR老板娘未发条码_{safe_contract}_{timestamp}.pdf"
            result = generate_barcode_pdf_from_excel(
                source_pdf=source,
                excel_path=Path(self.excel_var.get().strip()),
                contract_no=contract_no,
                output_pdf=output,
                extra_each_size=extra,
            )
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
            self.status_var.set("生成失败，请检查提示。")
            return

        self.status_var.set(f"已按未发货生成 {result.total_pages} 张")
        messagebox.showinfo(
            "生成完成",
            f"合同：{contract_no}\n\n打印 PDF：\n{result.output_pdf}\n\n数量明细：\n{result.manifest_path}\n\n合计：{result.total_pages} 张",
        )


def main() -> None:
    app = BarcodeApp()
    app.mainloop()


if __name__ == "__main__":
    main()

