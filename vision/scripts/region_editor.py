"""Edit cabinet and section rectangles in a single top-view window."""

import tkinter as tk
from tkinter import simpledialog, ttk

import cv2

from vision.section_regions import contains_bounds


LABELS = {'phone': '휴대폰', 'wallet': '지갑', 'usb': 'USB', 'lip_balm': '립밤',
          'hand_cream': '핸드크림', 'power_bank': '보조배터리'}
REGION_IDS = {name.casefold(): key for key, label in LABELS.items() for name in (key, label)}
COLORS = ('#67b9ff', '#ffd66b', '#81e3a5', '#fa9dc8', '#bfabff', '#ffab7d')


class RegionEditor:
    def __init__(self, root, image, saved, names):
        self.root = root
        self.saved = {**saved, 'regions': dict(saved['regions'])}
        self.names = [None, *dict.fromkeys([*names, *saved['regions']])]
        self.width, self.height = saved['image_size_px']
        scale = min(1, (root.winfo_screenwidth() - 280) / self.width,
                    (root.winfo_screenheight() - 220) / self.height)
        display = cv2.resize(image, (max(1, round(self.width * scale)), max(1, round(self.height * scale))),
                             interpolation=cv2.INTER_AREA)
        self.display_h, self.display_w = display.shape[:2]
        _, ppm = cv2.imencode('.ppm', display)
        self.photo = tk.PhotoImage(data=ppm.tobytes(), format='PPM')
        self.result = None
        self.start = self.pending = None

        root.title('보관함 구역 편집')
        self.prompt = tk.StringVar()
        self.message = tk.StringVar(value='드래그 후 Enter로 확정하세요. 목록에서 구역을 다시 선택할 수 있습니다.')
        ttk.Label(root, textvariable=self.prompt, padding=(12, 8), font=('맑은 고딕', 12, 'bold')).pack(anchor='w')
        body = ttk.Frame(root, padding=(12, 0))
        body.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(body, width=self.display_w, height=self.display_h, highlightthickness=0,
                                cursor='crosshair')
        self.canvas.pack(side='left', anchor='nw')
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        sidebar = ttk.Frame(body, padding=(10, 0, 0, 0))
        sidebar.pack(side='left', fill='y')
        tools = ttk.Frame(sidebar)
        tools.pack(fill='x', pady=(0, 6))
        ttk.Button(tools, text='구역 추가', command=self.add_region).pack(side='left')
        self.delete_button = ttk.Button(tools, text='선택 삭제', command=self.delete_region)
        self.delete_button.pack(side='right')
        self.listbox = tk.Listbox(sidebar, width=25, height=min(len(self.names), 16), exportselection=False)
        scrollbar = ttk.Scrollbar(sidebar, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.listbox.pack(side='left', fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.select_from_list)
        self.canvas.bind('<ButtonPress-1>', self.begin_drag)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.finish_drag)

        footer = ttk.Frame(root, padding=(12, 10))
        footer.pack(fill='x')
        ttk.Button(footer, text='확정 · Enter', command=self.confirm).pack(side='left')
        ttk.Button(footer, text='저장 · Ctrl+S', command=self.save).pack(side='left', padx=6)
        ttk.Button(footer, text='취소', command=root.destroy).pack(side='left')
        ttk.Label(footer, textvariable=self.message, wraplength=max(220, self.display_w - 160)).pack(side='left', padx=8)
        root.bind('<Return>', self.confirm)
        root.bind('<Control-s>', self.save)
        root.bind('<Escape>', lambda event: root.destroy())
        self.select(next((i for i, name in enumerate(self.names) if self.bounds(name) is None), 0))

    def label(self, name):
        return '보관함 전체' if name is None else LABELS.get(name, name)

    def bounds(self, name):
        return self.saved.get('cabinet_bounds_px') if name is None else self.saved['regions'].get(name)

    def select_from_list(self, event):
        selection = self.listbox.curselection()
        if selection and selection[0] != self.active:
            self.select(selection[0])

    def select(self, index):
        self.active = index
        self.start = self.pending = None
        self.prompt.set(f'{index + 1}/{len(self.names)}  {self.label(self.names[index])} 구역을 드래그하세요')
        self.delete_button.configure(state='normal' if index else 'disabled')
        self.redraw()

    def add_region(self):
        value = simpledialog.askstring('구역 추가', '품목 이름 또는 구역 ID를 입력하세요. 예: 휴대폰, wallet, USB',
                                       parent=self.root)
        if value is None:
            return
        value = value.strip()
        name = REGION_IDS.get(value.casefold(), value)
        if not name or name == self.label(None):
            self.message.set('보관함 전체와 구분되는 구역 이름을 입력하세요.')
            return
        if name in self.names:
            self.select(self.names.index(name))
            self.message.set('이미 있는 구역입니다. 이 구역을 다시 그릴 수 있습니다.')
            return
        self.names.append(name)
        self.select(len(self.names) - 1 if self.bounds(None) is not None else 0)
        self.message.set(f'{self.label(name)} 구역을 추가했습니다. 안내 순서대로 드래그하세요.')

    def delete_region(self):
        if self.active == 0:
            return
        name = self.names.pop(self.active)
        self.saved['regions'].pop(name, None)
        self.select(min(self.active, len(self.names) - 1))
        self.message.set(f'{self.label(name)} 구역을 삭제했습니다. 저장하면 파일에 반영됩니다.')

    def redraw(self):
        self.canvas.delete('region')
        self.listbox.delete(0, 'end')
        cabinet = self.bounds(None)
        for index, name in enumerate(self.names):
            bounds = self.bounds(name)
            color = '#ffffff' if name is None else COLORS[(index - 1) % len(COLORS)]
            outside = bounds is not None and name is not None and cabinet is not None and not contains_bounds(cabinet, bounds)
            status = '경계 밖' if outside else '완료' if bounds is not None else '미지정'
            self.listbox.insert('end', f'{self.label(name)}  ·  {status}')
            if bounds is not None:
                box = self.display_bounds(bounds)
                self.canvas.create_rectangle(*box, outline='#ff5555' if outside else color, width=2,
                                             dash=(7, 4) if name is None else (), tags='region')
                self.canvas.create_text(box[0] + 5, box[1] + 4, anchor='nw', text=self.label(name),
                                        fill=color, font=('맑은 고딕', 11, 'bold'), tags='region')
        self.listbox.selection_set(self.active)
        self.listbox.see(self.active)
        self.canvas.delete('pending')

    def display_bounds(self, bounds):
        x1, y1, x2, y2 = bounds
        return (x1 * self.display_w / self.width, y1 * self.display_h / self.height,
                x2 * self.display_w / self.width, y2 * self.display_h / self.height)

    def image_point(self, event):
        return (round(min(max(event.x, 0), self.display_w) * self.width / self.display_w),
                round(min(max(event.y, 0), self.display_h) * self.height / self.display_h))

    def begin_drag(self, event):
        self.start = self.image_point(event)
        self.pending = None
        self.canvas.delete('pending')

    def drag(self, event):
        if self.start is None:
            return
        x, y = self.image_point(event)
        left, right = sorted((self.start[0], x))
        top, bottom = sorted((self.start[1], y))
        self.pending = [left, top, right, bottom] if left < right and top < bottom else None
        self.canvas.delete('pending')
        if self.pending is not None:
            self.canvas.create_rectangle(*self.display_bounds(self.pending), outline='#ffcc00', width=3, tags='pending')

    def finish_drag(self, event):
        self.drag(event)
        self.start = None
        if self.pending is not None:
            self.message.set('Enter 또는 확정 버튼으로 이 구역을 적용하세요.')

    def confirm(self, event=None):
        if self.pending is None:
            self.message.set('사진 위에서 먼저 구역을 드래그하세요.')
            return
        name = self.names[self.active]
        if name is None:
            self.saved['cabinet_bounds_px'] = self.pending
        else:
            cabinet = self.bounds(None)
            if cabinet is None or not contains_bounds(cabinet, self.pending):
                self.message.set('품목 구역은 보관함 전체 경계 안에 그려야 합니다.')
                return
            self.saved['regions'][name] = self.pending
        self.select(min(self.active + 1, len(self.names) - 1))
        self.message.set('구역을 확정했습니다. 전체 배치를 확인한 뒤 저장하세요.')

    def save(self, event=None):
        if self.pending is not None:
            self.message.set('드래그한 구역을 Enter로 확정한 뒤 저장하세요.')
            return
        cabinet = self.bounds(None)
        for index, name in enumerate(self.names):
            bounds = self.bounds(name)
            if bounds is None or (name is not None and not contains_bounds(cabinet, bounds)):
                self.select(index)
                self.message.set('미지정 구역과 보관함 경계 밖 구역을 수정한 뒤 저장하세요.')
                return
        self.result = self.saved
        self.root.destroy()


def edit_regions(image, saved, names):
    root = tk.Tk()
    editor = RegionEditor(root, image, saved, names)
    root.mainloop()
    return editor.result
