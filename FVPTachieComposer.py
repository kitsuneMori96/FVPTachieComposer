import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import struct
import zlib
from PIL import Image, ImageTk
import os



# ---------- HZC 文件解析与转换 ----------
def parse_hzc_header(header_bytes):
	"""
	解析 HZC 文件头（44 字节）
	返回字典包含关键信息
	"""
	if len(header_bytes) < 44:
		raise ValueError("文件头不足 44 字节")

	magic = header_bytes[0:4].decode('ascii', errors='ignore')
	if magic != "hzc1":
		print(f"警告: 魔数不是 'hzc1'，实际为 {magic}")

	original_size = struct.unpack('<I', header_bytes[4:8])[0]
	image_type = struct.unpack('<H', header_bytes[18:20])[0]
	width = struct.unpack('<H', header_bytes[20:22])[0]
	height = struct.unpack('<H', header_bytes[22:24])[0]
	offset_x = struct.unpack('<H', header_bytes[24:26])[0]
	offset_y = struct.unpack('<H', header_bytes[26:28])[0]
	diff = struct.unpack('<I', header_bytes[32:36])[0]
	frame_count = diff if image_type == 2 else 1

	return {
		'magic': magic,
		'original_size': original_size,
		'image_type': image_type,
		'width': width,
		'height': height,
		'frame_count': frame_count,
		'offset_x': offset_x,
		'offset_y': offset_y,
	}

def transform_bytes_bytearray(data):
	"""
	字节变换函数（仅用于多帧 HZC）：每4个字节一组，交换位置0和2
	"""
	byte_arr = bytearray(data)
	for i in range(0, len(byte_arr), 4):
		if i + 3 < len(byte_arr):
			byte_arr[i], byte_arr[i+2] = byte_arr[i+2], byte_arr[i]
	return bytes(byte_arr)

def convert_hzc_data(hzc_data, original_filename, base_output_dir):
	"""
	将 HZC 二进制数据转换为 PNG 图片
	:param hzc_data: 完整的 HZC 文件数据
	:param original_filename: 原始文件名（不含扩展名）
	:param base_output_dir: 基础输出目录（例如 bin 文件名去掉后缀的目录）
	:return: 字典包含处理信息
	"""
	if len(hzc_data) < 44:
		print(f"错误: 文件数据过小，不是有效的 HZC 文件")
		return None

	header = parse_hzc_header(hzc_data[:44])
	image_type = header['image_type']
	width = header['width']
	height = header['height']
	frame_count = header['frame_count']
	offset_x = header['offset_x'] if header['image_type'] == 2 else None
	offset_y = header['offset_y'] if header['image_type'] == 2 else None

	# 确定输出文件夹
	is_emotion = original_filename.endswith('_表情')
	out_dir = Path(base_output_dir) / original_filename  # 统一以完整文件名作为文件夹名
	out_dir.mkdir(parents=True, exist_ok=True)

	# 解压数据
	compressed_data = hzc_data[44:]
	try:
		decompressed = zlib.decompress(compressed_data)
	except zlib.error as e:
		print(f"解压失败 {original_filename}: {e}")
		return None

	saved_paths = []

	if image_type == 2:  # 多帧（表情部件通常为此类）
		# 应用字节变换
		transformed = transform_bytes_bytearray(decompressed)
		bytes_per_frame = width * height * 4  # 每帧 RGBA 大小
		for i in range(frame_count):
			start = i * bytes_per_frame
			frame_data = transformed[start:start+bytes_per_frame]
			if len(frame_data) < bytes_per_frame:
				print(f"警告: 帧 {i} 数据不足，跳过")
				continue
			img = Image.frombytes('RGBA', (width, height), frame_data)
			out_filename = f"{original_filename}_{i:03d}.png"
			out_path = out_dir / out_filename
			img.save(out_path, 'PNG')
			saved_paths.append(str(out_path))
		print(f"已转换多帧: {original_filename} -> {out_dir} (共 {frame_count} 帧)")

	else:  # 单图 (image_type 0 或 1)
		if image_type == 0:  # 24位 BGR
			bytes_per_pixel = 3
			mode = 'RGB'
			expected = width * height * bytes_per_pixel
			if len(decompressed) != expected:
				print(f"警告: 数据大小不匹配，预期 {expected}，实际 {len(decompressed)}")
			img = Image.frombytes(mode, (width, height), decompressed)
			b, g, r = img.split()
			img = Image.merge("RGB", (r, g, b))
		else:  # 假设为 1 (32位 BGRA) 或其他
			bytes_per_pixel = 4
			mode = 'RGBA'
			img = Image.frombytes(mode, (width, height), decompressed)
			b, g, r, a = img.split()
			img = Image.merge("RGBA", (r, g, b, a))

		out_filename = f"{original_filename}.png"
		out_path = out_dir / out_filename
		img.save(out_path, 'PNG')
		saved_paths.append(str(out_path))
		print(f"已转换单图: {original_filename} -> {out_path}")

	# 返回处理信息
	return {
		'is_emotion': is_emotion,
		'base_dir': out_dir,
		'offset_x': offset_x,
		'offset_y': offset_y,
		'frame_count': frame_count,
		'saved_files': saved_paths
	}

# ---------- bin 文件解析 ----------
def parse_bin_info(input_file: str):
	"""
	解析.bin文件，返回文件信息列表。
	每个元素为字典：{'filename': 文件名（不含扩展名）, 'offset': 绝对偏移, 'size': 大小, 'type': 类型}
	"""
	with open(input_file, 'rb') as f:
		header = f.read(8)
		if len(header) != 8:
			raise ValueError("文件头不完整")
		x, y = struct.unpack('<II', header)  # 文件数，文件名总长度

		entries = []  # (rel_offset, abs_offset, size)
		for _ in range(x):
			entry_data = f.read(12)
			if len(entry_data) != 12:
				raise ValueError("文件信息表不完整")
			rel_offset, abs_offset, size = struct.unpack('<III', entry_data)
			entries.append((rel_offset, abs_offset, size))

		filenames_data = f.read(y)
		if len(filenames_data) != y:
			raise ValueError("文件名区域长度不符")

		# 解析所有文件名
		filenames = []
		for rel_offset, _, _ in entries:
			if rel_offset >= y:
				raise ValueError(f"无效的文件名偏移：{rel_offset}")
			start = rel_offset
			end = filenames_data.find(b'\x00', start)
			if end == -1:
				end = y
			filename_bytes = filenames_data[start:end]
			try:
				filename = filename_bytes.decode('shift-jis')
			except UnicodeDecodeError:
				filename = filename_bytes.decode('shift-jis', errors='replace')
			filenames.append(filename)

		# 预检测每个文件的类型（读取前4字节）
		file_types = []
		for idx, (_, abs_offset, size) in enumerate(entries):
			f.seek(abs_offset)
			header_bytes = f.read(4) if size >= 4 else b''
			if header_bytes == b'hzc1':
				typ = 'hzc'
			elif header_bytes == b'OggS':
				typ = 'ogg'
			elif header_bytes == b'RIFF':
				typ = 'wav'
			else:
				typ = 'bin'
			file_types.append(typ)

		# 构建返回列表
		file_infos = []
		for i, filename in enumerate(filenames):
			file_infos.append({
				'filename': filename,
				'offset': entries[i][1],
				'size': entries[i][2],
				'type': file_types[i]
			})
		return file_infos

# ---------- 层级细分选择 ----------
def interactive_filter_by_parts(file_infos):
	"""
	根据文件名下划线分割部分进行多级筛选。
	返回筛选后的 file_infos 列表。
	"""
	current_list = file_infos
	level = 2  # 从索引2开始（因为索引0="CHR"，索引1=角色名，已固定）

	while True:
		# 获取当前层级的所有可能值（只考虑文件名分割后长度 > level 的文件）
		values = set()
		for info in current_list:
			parts = info['filename'].split('_')
			if len(parts) > level:
				values.add(parts[level])
		sorted_values = sorted(values)
		if not sorted_values:
			print("没有更多细分层级，将处理当前所有文件。")
			break

		print(f"\n当前层级（第{level}部分）的可选值：")
		for i, val in enumerate(sorted_values, 1):
			print(f"{i}. {val}")
		print("0. 全选（处理当前所有文件）")

		choice = input("请选择序号：").strip()
		if choice == '0':
			break
		try:
			idx = int(choice) - 1
			if 0 <= idx < len(sorted_values):
				selected_val = sorted_values[idx]
				# 筛选出文件该部分等于 selected_val 的文件（只保留长度 > level 且值匹配的）
				new_list = [
					info for info in current_list
					if len(info['filename'].split('_')) > level and info['filename'].split('_')[level] == selected_val
				]
				if not new_list:
					print("选择后无文件，将保留原列表。")
					# 实际上不应发生，因为 selected_val 是从当前列表提取的
				else:
					current_list = new_list
				level += 1
				continue
			else:
				print(f"序号超出范围，应为 0~{len(sorted_values)}")
		except ValueError:
			print("输入无效，请输入数字。")
		# 如果输入无效，重新循环
	return current_list

# ---------- 提取并转换符合条件的文件 ----------
def extract_and_convert_by_condition(input_file, file_infos, output_dir, condition_func):
	"""
	从 bin 文件中读取符合条件的数据，并立即转换为 PNG
	返回转换后的信息列表（每个元素是 convert_hzc_data 的返回值）
	"""
	results = []
	with open(input_file, 'rb') as f:
		for info in file_infos:
			if not condition_func(info):
				continue
			f.seek(info['offset'])
			data = f.read(info['size'])
			if len(data) != info['size']:
				raise ValueError(f"文件 {info['filename']} 数据不完整")
			conv_info = convert_hzc_data(data, info['filename'], output_dir)
			if conv_info:
				results.append(conv_info)
	return results

# ---------- 差分合成 ----------
def compose_differentials(base_output_dir, converted_infos):
	"""
	根据转换后的信息，对每个底图及其对应的表情部件进行差分合成
	:param base_output_dir: 基础输出目录（同 convert_hzc_data 中的 base_output_dir）
	:param converted_infos: extract_and_convert_by_condition 返回的列表
	"""
	# 建立从部件文件夹路径到对应信息的映射
	emotion_map = {}
	base_infos = []  # 底图信息列表
	for info in converted_infos:
		if info['is_emotion']:
			emotion_map[str(info['base_dir'])] = info
		else:
			base_infos.append(info)

	for base_info in base_infos:
		base_dir = base_info['base_dir']
		base_filename = base_dir.name

		# 底图 PNG 路径
		base_img_path = base_dir / f"{base_filename}.png"
		if not base_img_path.exists():
			print(f"警告: 底图文件不存在 {base_img_path}")
			continue

		# 对应的表情部件文件夹（与底图同父目录，名为 base_filename + '_表情'）
		emotion_folder = base_dir.parent / (base_filename + "_表情")
		if str(emotion_folder) not in emotion_map:
			continue

		emotion_info = emotion_map[str(emotion_folder)]
		offset_x = emotion_info['offset_x']
		offset_y = emotion_info['offset_y']
		if offset_x is None or offset_y is None:
			print(f"警告: 部件文件夹 {emotion_folder} 缺少偏移信息，跳过")
			continue

		# 创建输出子文件夹 diff
		diff_dir = base_dir / "diff"
		diff_dir.mkdir(exist_ok=True)

		# 打开底图
		base_img = Image.open(base_img_path).convert("RGBA")

		# 遍历部件文件夹中的所有 PNG 文件（按文件名排序以确保顺序稳定）
		for png_path in sorted(emotion_folder.glob("*.png")):
			comp_img = Image.open(png_path).convert("RGBA")
			w, h = comp_img.size

			# 合成
			result = base_img.copy()
			paste_x, paste_y = offset_x, offset_y

			# 计算有效重叠区域
			overlap = (
				max(0, paste_x),
				max(0, paste_y),
				min(base_img.width, paste_x + w),
				min(base_img.height, paste_y + h)
			)
			if overlap[0] < overlap[2] and overlap[1] < overlap[3]:
				comp_crop = (
					overlap[0] - paste_x,
					overlap[1] - paste_y,
					overlap[2] - paste_x,
					overlap[3] - paste_y
				)
				comp_region = comp_img.crop(comp_crop)
				base_region = result.crop(overlap)
				blended = Image.alpha_composite(base_region, comp_region)
				result.paste(blended, overlap)

			# 保存结果
			out_filename = f"diff_{png_path.name}"
			out_path = diff_dir / out_filename
			result.save(out_path)
			print(f"已合成: {out_path}")

	print("差分合成完成！")

# ---------- 扩展解析：获取 HZC 头部信息 ----------
def parse_hzc_header_from_bytes(header_bytes):
	"""从44字节头部解析信息"""
	if len(header_bytes) < 44:
		return None
	magic = header_bytes[0:4].decode('ascii', errors='ignore')
	if magic != "hzc1":
		return None
	image_type = struct.unpack('<H', header_bytes[18:20])[0]
	width = struct.unpack('<H', header_bytes[20:22])[0]
	height = struct.unpack('<H', header_bytes[22:24])[0]
	offset_x = struct.unpack('<H', header_bytes[24:26])[0]
	offset_y = struct.unpack('<H', header_bytes[26:28])[0]
	diff = struct.unpack('<I', header_bytes[32:36])[0]
	frame_count = diff if image_type == 2 else 1
	return {
		'image_type': image_type,
		'width': width,
		'height': height,
		'offset_x': offset_x,
		'offset_y': offset_y,
		'frame_count': frame_count
	}

def parse_bin_info_extended(input_file):
	"""调用原 parse_bin_info 并补充 HZC 头部信息"""
	base_infos = parse_bin_info(input_file)  # 原函数返回列表，每个元素含 filename, offset, size, type
	with open(input_file, 'rb') as f:
		for info in base_infos:
			if info['type'] == 'hzc':
				f.seek(info['offset'])
				header_data = f.read(44)
				header_info = parse_hzc_header_from_bytes(header_data)
				if header_info:
					info.update(header_info)
				else:
					info.update({'image_type': 0, 'width': 0, 'height': 0, 'offset_x': 0, 'offset_y': 0, 'frame_count': 1})
			else:
				info.update({'image_type': None, 'width': 0, 'height': 0, 'offset_x': 0, 'offset_y': 0, 'frame_count': 1})
	return base_infos

# ---------- 将 HZC 数据转换为 PIL 图像列表 ----------
def hzc_data_to_pil_list(hzc_data, header_info):
	"""
	根据 HZC 数据和头部信息，返回 PIL Image 列表
	header_info 应包含 image_type, width, height, frame_count
	"""
	if len(hzc_data) < 44:
		return []
	compressed = hzc_data[44:]
	try:
		decompressed = zlib.decompress(compressed)
	except zlib.error:
		return []
	image_type = header_info['image_type']
	width = header_info['width']
	height = header_info['height']
	frame_count = header_info['frame_count']

	if image_type == 2:  # 多帧
		transformed = transform_bytes_bytearray(decompressed)
		bytes_per_frame = width * height * 4
		images = []
		for i in range(frame_count):
			start = i * bytes_per_frame
			frame_data = transformed[start:start+bytes_per_frame]
			if len(frame_data) < bytes_per_frame:
				break
			img = Image.frombytes('RGBA', (width, height), frame_data)
			images.append(img)
		return images
	else:
		if image_type == 0:  # 24位
			bytes_per_pixel = 3
			mode = 'RGB'
			expected = width * height * bytes_per_pixel
			if len(decompressed) != expected:
				decompressed = decompressed[:expected]
			img = Image.frombytes(mode, (width, height), decompressed)
			b, g, r = img.split()
			img = Image.merge("RGB", (r, g, b))
		else:  # 32位
			bytes_per_pixel = 4
			mode = 'RGBA'
			expected = width * height * bytes_per_pixel
			if len(decompressed) != expected:
				decompressed = decompressed[:expected]
			img = Image.frombytes(mode, (width, height), decompressed)
			b, g, r, a = img.split()
			img = Image.merge("RGBA", (r, g, b, a))
		return [img]

# ---------- 合成差分图像 ----------
def compose_preview(base_img, part_img, offset_x, offset_y):
	"""将部件图像合成到底图上，返回合成后的 PIL Image"""
	base = base_img.convert('RGBA')
	part = part_img.convert('RGBA')
	result = base.copy()
	w, h = part.size
	paste_x, paste_y = offset_x, offset_y
	# 计算有效重叠区域
	overlap = (
		max(0, paste_x),
		max(0, paste_y),
		min(base.width, paste_x + w),
		min(base.height, paste_y + h)
	)
	if overlap[0] < overlap[2] and overlap[1] < overlap[3]:
		comp_crop = (
			overlap[0] - paste_x,
			overlap[1] - paste_y,
			overlap[2] - paste_x,
			overlap[3] - paste_y
		)
		comp_region = part.crop(comp_crop)
		base_region = result.crop(overlap)
		blended = Image.alpha_composite(base_region, comp_region)
		result.paste(blended, overlap)
	return result

# ---------- GUI 主类 ----------
class HZCGUI:
	def __init__(self, root):
		self.root = root
		self.root.title("FVP引擎 立绘查看与合成工具")
		self.root.geometry("1600x900")  

		# 变量
		self.input_file = None
		self.file_infos = []		  # 所有文件信息
		self.role_dict = {}			# 角色名 -> 文件信息列表
		self.current_preview_images = []  # 当前预览的图像列表（PIL）
		self.current_preview_index = 0	# 当前显示的帧索引
		self.current_part_info = None	 # 当前选择的部件信息
		self.current_composed_image = None  # 当前合成的图像（PIL）

		# 创建菜单
		menubar = tk.Menu(root)
		file_menu = tk.Menu(menubar, tearoff=0)
		file_menu.add_command(label="打开 BIN 文件", command=self.open_file)
		file_menu.add_separator()
		file_menu.add_command(label="退出", command=root.quit)
		menubar.add_cascade(label="文件", menu=file_menu)

		help_menu = tk.Menu(menubar, tearoff=0)
		help_menu.add_command(label="使用说明", command=self.show_help)
		menubar.add_cascade(label="帮助", menu=help_menu)

		root.config(menu=menubar)

		# 主布局：三栏
		main_pane = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
		main_pane.pack(fill=tk.BOTH, expand=True)

		# 左侧：角色树（带滚动条）
		left_frame = ttk.Frame(main_pane, width=250)
		main_pane.add(left_frame, weight=1)
		ttk.Label(left_frame, text="角色列表").pack(anchor=tk.W)

		# 创建带滚动条的树视图容器
		tree_container = ttk.Frame(left_frame)
		tree_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

		# 垂直滚动条
		tree_scrollbar = ttk.Scrollbar(tree_container)
		tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

		# 树视图
		self.tree = ttk.Treeview(tree_container, columns=("type",), show="tree",
								 yscrollcommand=tree_scrollbar.set)
		self.tree.heading("#0", text="名称")
		self.tree.column("#0", width=200)  # 留出滚动条空间
		self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

		# 关联滚动条
		tree_scrollbar.config(command=self.tree.yview)

		self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

		# 中间：预览与合成控制区
		mid_frame = ttk.Frame(main_pane)
		main_pane.add(mid_frame, weight=2)

		# 底图预览区域
		base_preview_frame = ttk.LabelFrame(mid_frame, text="底图预览")
		base_preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

		self.preview_label = ttk.Label(base_preview_frame, text="请选择一个底图文件")
		self.preview_label.pack(pady=10)

		self.frame_control = ttk.Frame(base_preview_frame)
		self.frame_control.pack()
		self.prev_btn = ttk.Button(self.frame_control, text="上一帧", command=self.prev_frame, state=tk.DISABLED)
		self.prev_btn.pack(side=tk.LEFT, padx=5)
		self.frame_label = ttk.Label(self.frame_control, text="帧 0/0")
		self.frame_label.pack(side=tk.LEFT, padx=5)
		self.next_btn = ttk.Button(self.frame_control, text="下一帧", command=self.next_frame, state=tk.DISABLED)
		self.next_btn.pack(side=tk.LEFT, padx=5)

		# 部件预览区域
		part_preview_frame = ttk.LabelFrame(mid_frame, text="部件预览")
		part_preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

		# 部件选择行
		select_row = ttk.Frame(part_preview_frame)
		select_row.pack(fill=tk.X, pady=5)
		ttk.Label(select_row, text="选择表情部件:").pack(side=tk.LEFT)
		self.part_var = tk.StringVar()
		self.part_combo = ttk.Combobox(select_row, textvariable=self.part_var, state="readonly", width=30)
		self.part_combo.pack(side=tk.LEFT, padx=5)
		self.part_combo.bind("<<ComboboxSelected>>", self.on_part_select)

		# 部件预览图像
		self.part_preview_label = ttk.Label(part_preview_frame)
		self.part_preview_label.pack(pady=5)

		# 操作按钮行
		btn_row = ttk.Frame(part_preview_frame)
		btn_row.pack(fill=tk.X, pady=5)
		self.preview_part_btn = ttk.Button(btn_row, text="预览部件", command=self.preview_part, state=tk.DISABLED)
		self.preview_part_btn.pack(side=tk.LEFT, padx=5)
		self.compose_btn = ttk.Button(btn_row, text="合成预览", command=self.compose_preview, state=tk.DISABLED)
		self.compose_btn.pack(side=tk.LEFT, padx=5)

		# 右侧：合成结果预览区
		right_frame = ttk.Frame(main_pane)
		main_pane.add(right_frame, weight=2)

		compose_result_frame = ttk.LabelFrame(right_frame, text="合成预览结果")
		compose_result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

		self.compose_img_label = ttk.Label(compose_result_frame)
		self.compose_img_label.pack(pady=10)

		# 保存按钮行
		save_row = ttk.Frame(compose_result_frame)
		save_row.pack(fill=tk.X, pady=5)
		save_btn = ttk.Button(save_row, text="保存合成图", command=self.save_composed)
		save_btn.pack(side=tk.LEFT, padx=5)
		compose_all_btn = ttk.Button(save_row, text="合成所有差分", command=self.compose_all_diffs)
		compose_all_btn.pack(side=tk.LEFT, padx=5)

		# 状态栏
		self.status = ttk.Label(root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
		self.status.pack(side=tk.BOTTOM, fill=tk.X)

	def show_help(self):
		"""显示使用说明"""
		help_text = """
使用说明：
0. 实际上，这个小工具可以打开的文件不局限于立绘文件，虽然最开始研发的目的是立绘合成。
1. 点击菜单“文件”->“打开 BIN 文件”，选择一个 .bin 文件。
2. 解析完成后，左侧树形列表按角色显示所有底图 HZC 文件。
3. 点击底图文件，中间区域会显示底图预览，下方部件下拉框会列出对应的表情部件帧。
4. 选择部件帧后，可点击“预览部件”查看部件单独图像。
5. 点击“合成预览”可在右侧查看合成效果。
6. 如需保存当前合成图，点击“保存合成图”。
7. 如需批量保存该底图的所有表情差分，点击“合成所有差分”，选择保存目录后自动生成所有帧的合成图。

注意：合成所有差分时，将使用部件文件的所有帧进行合成，并保存为 PNG 文件。
		"""
		messagebox.showinfo("使用说明", help_text)

	def open_file(self):
		file_path = filedialog.askopenfilename(
			title="选择 BIN 文件",
			filetypes=[("BIN files", "*.bin"), ("All files", "*.*")]
		)
		if not file_path:
			return
		self.input_file = file_path
		self.status.config(text=f"正在解析: {file_path}")
		self.root.update_idletasks()

		try:
			# 解析文件信息
			self.file_infos = parse_bin_info_extended(file_path)
		except Exception as e:
			messagebox.showerror("错误", f"解析失败: {e}")
			self.status.config(text="就绪")
			return

		# 按角色分类
		self.role_dict.clear()
		for info in self.file_infos:
			if info['type'] != 'hzc':
				continue
			parts = info['filename'].split('_')
			if len(parts) >= 2 and parts[0] == 'CHR':
				role = parts[1]
			else:
				role = "其他"
			self.role_dict.setdefault(role, []).append(info)

		# 更新树
		self.tree.delete(*self.tree.get_children())
		for role, infos in sorted(self.role_dict.items()):
			role_node = self.tree.insert("", "end", text=role, open=True)
			for info in sorted(infos, key=lambda x: x['filename']):
				# 判断是否为表情部件
				if not info['filename'].endswith('_表情'):
					
					node_text = info['filename']
					self.tree.insert(role_node, "end", text=node_text, values=(info['type'],), iid=info['filename'])

		self.status.config(text=f"加载完成，共 {len(self.file_infos)} 个文件")
		self.clear_preview()

	def clear_preview(self):
		"""清空所有预览图像"""
		self.preview_label.config(image='', text='请选择一个底图文件')
		self.preview_label.image = None
		self.frame_label.config(text="帧 0/0")
		self.prev_btn.config(state=tk.DISABLED)
		self.next_btn.config(state=tk.DISABLED)
		self.current_preview_images = []
		self.current_preview_index = 0
		self.part_combo.set('')
		self.part_combo.config(values=[])
		self.preview_part_btn.config(state=tk.DISABLED)
		self.compose_btn.config(state=tk.DISABLED)
		self.part_preview_label.config(image='')
		self.part_preview_label.image = None
		self.compose_img_label.config(image='')
		self.compose_img_label.image = None
		self.current_composed_image = None

	def on_tree_select(self, event):
		selected = self.tree.selection()
		if not selected:
			return
		item = selected[0]
		filename = item
		info = next((i for i in self.file_infos if i['filename'] == filename), None)
		if not info or info['type'] != 'hzc':
			return

		# 如果是表情文件，不预览底图，仅清空预览区并提示
		if filename.endswith('_表情'):
			self.clear_preview()
			self.preview_label.config(text="表情文件请在合成区预览")
			return

		# 否则是底图，正常预览
		try:
			with open(self.input_file, 'rb') as f:
				f.seek(info['offset'])
				data = f.read(info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取文件失败: {e}")
			return

		header_info = {
			'image_type': info.get('image_type', 0),
			'width': info.get('width', 0),
			'height': info.get('height', 0),
			'frame_count': info.get('frame_count', 1)
		}
		self.current_preview_images = hzc_data_to_pil_list(data, header_info)
		if not self.current_preview_images:
			messagebox.showerror("错误", "无法解析 HZC 图像")
			return

		self.current_preview_index = 0
		self.show_current_frame()

		if len(self.current_preview_images) > 1:
			self.prev_btn.config(state=tk.NORMAL)
			self.next_btn.config(state=tk.NORMAL)
		else:
			self.prev_btn.config(state=tk.DISABLED)
			self.next_btn.config(state=tk.DISABLED)

		self.update_part_combo(info)

	def show_current_frame(self):
		if not self.current_preview_images:
			return
		img = self.current_preview_images[self.current_preview_index]
		# 缩放以适应预览区域（最大宽度350）
		img.thumbnail((350, 350))
		photo = ImageTk.PhotoImage(img)
		self.preview_label.config(image=photo, text='')
		self.preview_label.image = photo
		self.frame_label.config(text=f"帧 {self.current_preview_index+1}/{len(self.current_preview_images)}")

	def prev_frame(self):
		if self.current_preview_index > 0:
			self.current_preview_index -= 1
			self.show_current_frame()

	def next_frame(self):
		if self.current_preview_index < len(self.current_preview_images) - 1:
			self.current_preview_index += 1
			self.show_current_frame()

	def update_part_combo(self, base_info):
		"""根据当前选中的底图，找出对应的表情部件文件，填充下拉框"""
		part_filename = base_info['filename'] + "_表情"
		part_info = next((i for i in self.file_infos if i['filename'] == part_filename and i['type'] == 'hzc'), None)
		if not part_info:
			self.part_combo.set('')
			self.part_combo.config(values=[])
			self.preview_part_btn.config(state=tk.DISABLED)
			self.compose_btn.config(state=tk.DISABLED)
			return

		frame_count = part_info.get('frame_count', 1)
		items = [f"{part_filename} - 帧 {i}" for i in range(frame_count)]
		self.part_combo.config(values=items)
		self.part_combo.set(items[0] if items else '')
		self.preview_part_btn.config(state=tk.NORMAL)
		self.compose_btn.config(state=tk.NORMAL)
		self.current_part_info = part_info

	def on_part_select(self, event):
		pass  # 可留空，选择后即可预览或合成

	def preview_part(self):
		"""预览当前选中的部件帧"""
		if not hasattr(self, 'current_part_info') or not self.current_part_info:
			return
		part_info = self.current_part_info
		part_selection = self.part_combo.get()
		if not part_selection:
			return
		try:
			frame_str = part_selection.split(' - 帧 ')[-1]
			frame_idx = int(frame_str)
		except:
			frame_idx = 0

		try:
			with open(self.input_file, 'rb') as f:
				f.seek(part_info['offset'])
				part_data = f.read(part_info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取部件文件失败: {e}")
			return

		part_header = {
			'image_type': part_info.get('image_type', 0),
			'width': part_info.get('width', 0),
			'height': part_info.get('height', 0),
			'frame_count': part_info.get('frame_count', 1)
		}
		part_imgs = hzc_data_to_pil_list(part_data, part_header)
		if not part_imgs or frame_idx >= len(part_imgs):
			messagebox.showerror("错误", "无法解析部件或帧索引无效")
			return
		part_img = part_imgs[frame_idx]

		part_img.thumbnail((300, 300))
		photo = ImageTk.PhotoImage(part_img)
		self.part_preview_label.config(image=photo)
		self.part_preview_label.image = photo

	def compose_preview(self):
		"""执行合成预览，结果显示在右侧"""
		if not hasattr(self, 'current_part_info') or not self.current_part_info:
			return

		selected = self.tree.selection()
		if not selected:
			return
		base_filename = selected[0]
		base_info = next((i for i in self.file_infos if i['filename'] == base_filename), None)
		if not base_info:
			return

		part_info = self.current_part_info
		part_selection = self.part_combo.get()
		if not part_selection:
			return
		try:
			frame_str = part_selection.split(' - 帧 ')[-1]
			frame_idx = int(frame_str)
		except:
			frame_idx = 0

		# 读取底图
		try:
			with open(self.input_file, 'rb') as f:
				f.seek(base_info['offset'])
				base_data = f.read(base_info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取底图文件失败: {e}")
			return

		base_header = {
			'image_type': base_info.get('image_type', 0),
			'width': base_info.get('width', 0),
			'height': base_info.get('height', 0),
			'frame_count': base_info.get('frame_count', 1)
		}
		base_imgs = hzc_data_to_pil_list(base_data, base_header)
		if not base_imgs:
			messagebox.showerror("错误", "无法解析底图")
			return
		base_img = base_imgs[0]

		# 读取部件
		try:
			with open(self.input_file, 'rb') as f:
				f.seek(part_info['offset'])
				part_data = f.read(part_info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取部件文件失败: {e}")
			return

		part_header = {
			'image_type': part_info.get('image_type', 0),
			'width': part_info.get('width', 0),
			'height': part_info.get('height', 0),
			'frame_count': part_info.get('frame_count', 1)
		}
		part_imgs = hzc_data_to_pil_list(part_data, part_header)
		if not part_imgs or frame_idx >= len(part_imgs):
			messagebox.showerror("错误", "无法解析部件或帧索引无效")
			return
		part_img = part_imgs[frame_idx]

		offset_x = part_info.get('offset_x', 0)
		offset_y = part_info.get('offset_y', 0)
		composed = compose_preview(base_img, part_img, offset_x, offset_y)
		self.current_composed_image = composed.copy()  # 保存原图用于保存

		# 缩放显示在右侧
		display_img = composed.copy()
		display_img.thumbnail((500, 500))
		photo = ImageTk.PhotoImage(display_img)
		self.compose_img_label.config(image=photo)
		self.compose_img_label.image = photo

	def save_composed(self):
		"""保存当前合成图像到文件，如果没有部件则直接保存底图"""
		selected = self.tree.selection()
		if not selected:
			messagebox.showwarning("警告", "请先选择一个底图文件。")
			return
		base_filename = selected[0]
		base_info = next((i for i in self.file_infos if i['filename'] == base_filename), None)
		if not base_info or base_info['type'] != 'hzc' or base_filename.endswith('_表情'):
			messagebox.showwarning("警告", "请选择一个非表情的底图文件。")
			return

		# 检查是否有对应部件
		part_filename = base_filename + "_表情"
		part_info = next((i for i in self.file_infos if i['filename'] == part_filename and i['type'] == 'hzc'), None)

		if not part_info:
			# 没有部件，直接保存底图
			try:
				with open(self.input_file, 'rb') as f:
					f.seek(base_info['offset'])
					base_data = f.read(base_info['size'])
			except Exception as e:
				messagebox.showerror("错误", f"读取底图文件失败: {e}")
				return

			base_header = {
				'image_type': base_info.get('image_type', 0),
				'width': base_info.get('width', 0),
				'height': base_info.get('height', 0),
				'frame_count': base_info.get('frame_count', 1)
			}
			base_imgs = hzc_data_to_pil_list(base_data, base_header)
			if not base_imgs:
				messagebox.showerror("错误", "无法解析底图")
				return
			base_img = base_imgs[0]  # 取第一帧

			file_path = filedialog.asksaveasfilename(
				defaultextension=".png",
				filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
				title="保存底图",
				initialfile=f"{base_filename}.png"
			)
			if not file_path:
				return
			try:
				base_img.save(file_path, "PNG")
				messagebox.showinfo("成功", f"底图已保存至: {file_path}")
			except Exception as e:
				messagebox.showerror("错误", f"保存失败: {e}")
		else:
			# 有部件，需要合成预览图像（现有逻辑）
			if self.current_composed_image is None:
				messagebox.showwarning("警告", "请先进行合成预览。")
				return
			file_path = filedialog.asksaveasfilename(
				defaultextension=".png",
				filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
				title="保存合成图像"
			)
			if not file_path:
				return
			try:
				self.current_composed_image.save(file_path, "PNG")
				messagebox.showinfo("成功", f"图像已保存至: {file_path}")
			except Exception as e:
				messagebox.showerror("错误", f"保存失败: {e}")

	def compose_all_diffs(self):
		"""合成当前底图对应的所有表情部件帧，并批量保存；若无部件则直接保存底图"""
		selected = self.tree.selection()
		if not selected:
			messagebox.showwarning("警告", "请先选择一个底图文件。")
			return
		base_filename = selected[0]
		base_info = next((i for i in self.file_infos if i['filename'] == base_filename), None)
		if not base_info or base_info['type'] != 'hzc' or base_filename.endswith('_表情'):
			messagebox.showwarning("警告", "请选择一个非表情的底图文件。")
			return

		# 获取对应的部件信息
		part_filename = base_filename + "_表情"
		part_info = next((i for i in self.file_infos if i['filename'] == part_filename and i['type'] == 'hzc'), None)

		# 选择保存目录
		save_dir = filedialog.askdirectory(title="选择保存图像的目录")
		if not save_dir:
			return

		# 读取底图数据
		try:
			with open(self.input_file, 'rb') as f:
				f.seek(base_info['offset'])
				base_data = f.read(base_info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取底图文件失败: {e}")
			return

		base_header = {
			'image_type': base_info.get('image_type', 0),
			'width': base_info.get('width', 0),
			'height': base_info.get('height', 0),
			'frame_count': base_info.get('frame_count', 1)
		}
		base_imgs = hzc_data_to_pil_list(base_data, base_header)
		if not base_imgs:
			messagebox.showerror("错误", "无法解析底图")
			return
		base_img = base_imgs[0]  # 取第一帧

		if not part_info:
			# 没有部件，直接保存底图
			out_filename = f"{base_filename}.png"
			out_path = os.path.join(save_dir, out_filename)
			try:
				base_img.save(out_path, "PNG")
				messagebox.showinfo("完成", f"图像已保存到:\n{out_path}")
			except Exception as e:
				messagebox.showerror("错误", f"保存文件失败: {e}")
			return  # 关键：函数结束，避免后续代码

		# 有部件，合成所有部件帧
		try:
			with open(self.input_file, 'rb') as f:
				f.seek(part_info['offset'])
				part_data = f.read(part_info['size'])
		except Exception as e:
			messagebox.showerror("错误", f"读取部件文件失败: {e}")
			return

		part_header = {
			'image_type': part_info.get('image_type', 0),
			'width': part_info.get('width', 0),
			'height': part_info.get('height', 0),
			'frame_count': part_info.get('frame_count', 1)
		}
		part_imgs = hzc_data_to_pil_list(part_data, part_header)
		if not part_imgs:
			messagebox.showerror("错误", "无法解析部件图像")
			return

		offset_x = part_info.get('offset_x', 0)
		offset_y = part_info.get('offset_y', 0)

		saved_count = 0
		for idx, part_img in enumerate(part_imgs):
			composed = compose_preview(base_img, part_img, offset_x, offset_y)
			out_filename = f"{base_filename}_diff_{idx:03d}.png"
			out_path = os.path.join(save_dir, out_filename)
			try:
				composed.save(out_path, "PNG")
				saved_count += 1
			except Exception as e:
				messagebox.showerror("错误", f"保存文件 {out_filename} 失败: {e}")
				break

		messagebox.showinfo("完成", f"成功保存 {saved_count} 个合成图像到目录:\n{save_dir}")

# ---------- 启动 ----------
if __name__ == '__main__':
	root = tk.Tk()
	app = HZCGUI(root)
	root.mainloop()