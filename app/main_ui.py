import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import sys
import os
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)
import io
import shutil
import re
import queue

# Import the processors
from controller import TranslationController
from course_auditor import CourseAuditor

class RedirectText:
    def __init__(self, text_ctrl, progress_bar, root):
        self.output = text_ctrl
        self.progress_bar = progress_bar
        self.root = root

    def write(self, string):
        # Update progress bar if tqdm prints a percentage
        match = re.search(r'(\d+)%', string)
        if match:
            pct = int(match.group(1))
            self.root.after(0, self._update_progress, pct)

        if '\r' in string:
            # Handle tqdm progress bars replacing the current line
            self.root.after(0, self._delete_last_and_insert, string)
        else:
            self.root.after(0, self._insert_text, string)
            
    def _update_progress(self, pct):
        self.progress_bar['value'] = pct
        self.progress_bar.update()

    def _delete_last_and_insert(self, string):
        self.output.delete("end-2c linestart", "end-1c")
        string = string.replace('\r', '')
        self.output.insert(tk.END, string)
        self.output.see(tk.END)

    def _insert_text(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)
        
    def flush(self):
        pass

class CourseTranslationHubUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Course Translation Hub")
        self.root.geometry("850x700")
        
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.hub_dir = os.path.dirname(self.app_dir)
        
        # Configure Grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # Top Frame for Buttons
        self.top_frame = ttk.Frame(self.root, padding="10")
        self.top_frame.grid(row=0, column=0, sticky="ew")

        # Title
        self.title_label = ttk.Label(self.top_frame, text="Course Translation Hub", font=("Helvetica", 18, "bold"))
        self.title_label.pack(pady=10)

        # Translation Section
        self.trans_frame = ttk.LabelFrame(self.top_frame, text="Translation Process", padding="10")
        self.trans_frame.pack(fill="x", pady=10)
        
        self.lang_var = tk.StringVar(value="PTBR")
        
        ttk.Radiobutton(self.trans_frame, text="Portuguese (PTBR)", variable=self.lang_var, value="PTBR").pack(side="left", padx=10)
        ttk.Radiobutton(self.trans_frame, text="Spanish (ES)", variable=self.lang_var, value="ES").pack(side="left", padx=10)
        
        self.trans_btn = ttk.Button(self.trans_frame, text="Select Course & Translate", command=self.run_translation)
        self.trans_btn.pack(side="right", padx=10)

        # Audit Section
        self.audit_frame = ttk.LabelFrame(self.top_frame, text="Quality Assurance Audit", padding="10")
        self.audit_frame.pack(fill="x", pady=10)

        self.audit_btn = ttk.Button(self.audit_frame, text="Select Courses & Audit", command=self.run_audit)
        self.audit_btn.pack(side="right", padx=10)

        # Progress Bar
        self.progress = ttk.Progressbar(self.top_frame, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(fill="x", pady=15)

        # Console Output
        self.console_frame = ttk.Frame(self.root, padding="10")
        self.console_frame.grid(row=1, column=0, sticky="nsew")
        
        self.console_label = ttk.Label(self.console_frame, text="Console Output:")
        self.console_label.pack(anchor="w")

        # Scrollbar for console
        self.scrollbar = tk.Scrollbar(self.console_frame)
        self.scrollbar.pack(side="right", fill="y")

        self.console = tk.Text(self.console_frame, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 12), yscrollcommand=self.scrollbar.set)
        self.console.pack(fill="both", expand=True)
        self.scrollbar.config(command=self.console.yview)

        # Redirect stdout and stderr
        redir = RedirectText(self.console, self.progress, self.root)
        sys.stdout = redir
        sys.stderr = redir

        print("Welcome to the Course Translation Hub!")
        print("Please select an operation above to begin.\n")

    def disable_buttons(self):
        self.trans_btn.config(state="disabled")
        self.audit_btn.config(state="disabled")
        self.progress['value'] = 0

    def enable_buttons(self):
        self.trans_btn.config(state="normal")
        self.audit_btn.config(state="normal")

    def _copy_to_workspace(self, src_path, target_folder):
        """Copies the selected file into the internal workspace folder and returns the new path."""
        target_dir = os.path.join(self.hub_dir, target_folder)
        os.makedirs(target_dir, exist_ok=True)
        filename = os.path.basename(src_path)
        dest_path = os.path.join(target_dir, filename)
        
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            print(f"Copying {filename} to {target_folder}...")
            shutil.copy2(src_path, dest_path)
            
        return dest_path

    def run_translation(self):
        translate_dir = os.path.join(self.hub_dir, "Courses to Translate")
        os.makedirs(translate_dir, exist_ok=True)
        
        imscc_paths = filedialog.askopenfilenames(
            initialdir=translate_dir,
            title="Select IMSCC Files to Translate",
            filetypes=[("IMSCC Files", "*.imscc")]
        )
        if not imscc_paths:
            return

        lang = self.lang_var.get()
        self.disable_buttons()
        print(f"\n======================================")
        print(f"Starting Translation to {lang}")
        print(f"Selected {len(imscc_paths)} file(s).")
        for p in imscc_paths:
            print(f" - {os.path.basename(p)}")
        print(f"======================================\n")

        def ask_user_for_link(unmapped_url, context_file):
            result_queue = queue.Queue()
            def show_dialog():
                dialog = tk.Toplevel(self.root)
                dialog.title("Unmapped Link Found")
                dialog_width = 550
                dialog_height = 320
                screen_width = dialog.winfo_screenwidth()
                screen_height = dialog.winfo_screenheight()
                x = int((screen_width - dialog_width) / 2)
                y = int((screen_height - dialog_height) / 2)
                dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
                dialog.transient(self.root)
                dialog.grab_set()

                lbl1 = ttk.Label(dialog, text=f"Found unmapped English link in {context_file}:")
                lbl1.pack(pady=(15, 5), padx=15, anchor="w")

                url_frame = ttk.Frame(dialog)
                url_frame.pack(fill='x', padx=15, pady=5)

                url_entry = ttk.Entry(url_frame)
                url_entry.insert(0, unmapped_url)
                url_entry.configure(state='readonly')
                url_entry.pack(side='left', fill='x', expand=True)

                def copy_link():
                    self.root.clipboard_clear()
                    self.root.clipboard_append(unmapped_url)
                    self.root.update()
                    
                copy_btn = ttk.Button(url_frame, text="Copy", command=copy_link, width=6)
                copy_btn.pack(side='left', padx=(5, 0))

                lbl2 = ttk.Label(dialog, text="Please enter the translated version:")
                lbl2.pack(pady=(10, 5), padx=15, anchor="w")

                input_entry = ttk.Entry(dialog)
                input_entry.pack(fill='x', padx=15, pady=5)
                input_entry.focus_set()

                lbl3 = ttk.Label(dialog, text="Optional Comment (will appear in report):")
                lbl3.pack(pady=(10, 5), padx=15, anchor="w")

                comment_entry = ttk.Entry(dialog)
                comment_entry.pack(fill='x', padx=15, pady=5)

                result = [None]
                def on_ok(event=None):
                    val = input_entry.get().strip()
                    comment = comment_entry.get().strip()
                    if not val:
                        from tkinter import messagebox
                        messagebox.showwarning("Missing Link", "Please enter a link, or click Skip.", parent=dialog)
                        return
                    result[0] = (val, comment)
                    dialog.destroy()
                    
                def on_skip(event=None):
                    comment = comment_entry.get().strip()
                    result[0] = (None, comment)
                    dialog.destroy()

                btn_frame = ttk.Frame(dialog)
                btn_frame.pack(pady=15)
                ttk.Button(btn_frame, text="OK", command=on_ok).pack(side="left", padx=5)
                ttk.Button(btn_frame, text="Skip", command=on_skip).pack(side="left", padx=5)

                dialog.bind('<Return>', on_ok)
                dialog.bind('<Escape>', on_skip)

                self.root.wait_window(dialog)
                result_queue.put(result[0])
            self.root.after(0, show_dialog)
            return result_queue.get()

        def thread_target():
            try:
                for idx, imscc_path in enumerate(imscc_paths, 1):
                    print(f"\n--- Processing File {idx}/{len(imscc_paths)}: {os.path.basename(imscc_path)} ---")
                    workspace_path = self._copy_to_workspace(imscc_path, "Courses to Translate")
                    controller = TranslationController(
                        target_language=lang, 
                        imscc_path=workspace_path,
                        link_prompt_callback=ask_user_for_link
                    )
                    controller.process_directory()
                    controller.update_excel_dashboard()
                self.progress['value'] = 100
                print("\n=== All Translations Completed Successfully! ===")
            except Exception as e:
                print(f"\n=== Error during translation: {e} ===")
            finally:
                self.root.after(0, self.enable_buttons)

        threading.Thread(target=thread_target, daemon=True).start()

    def run_audit(self):
        audit_dir = os.path.join(self.hub_dir, "Courses to Audit")
        os.makedirs(audit_dir, exist_ok=True)
        
        en_imscc = filedialog.askopenfilename(
            initialdir=audit_dir,
            title="Select ORIGINAL English IMSCC File",
            filetypes=[("IMSCC Files", "*.imscc")]
        )
        if not en_imscc:
            return

        pt_imscc = filedialog.askopenfilename(
            initialdir=audit_dir,
            title="Select TRANSLATED IMSCC File",
            filetypes=[("IMSCC Files", "*.imscc")]
        )
        if not pt_imscc:
            return

        self.disable_buttons()
        print(f"\n======================================")
        print(f"Starting QA Audit")
        print(f"Original: {en_imscc}")
        print(f"Translated: {pt_imscc}")
        print(f"======================================\n")

        def thread_target():
            try:
                en_workspace_path = self._copy_to_workspace(en_imscc, "Courses to Audit")
                pt_workspace_path = self._copy_to_workspace(pt_imscc, "Courses to Audit")
                
                auditor = CourseAuditor(en_workspace_path, pt_workspace_path)
                auditor.run_audit()
                self.progress['value'] = 100
                print("\n=== Audit Completed Successfully! ===")
            except Exception as e:
                print(f"\n=== Error during audit: {e} ===")
            finally:
                self.root.after(0, self.enable_buttons)

        threading.Thread(target=thread_target, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = CourseTranslationHubUI(root)
    root.mainloop()
