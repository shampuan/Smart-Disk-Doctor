#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
import os
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QListWidget, QListWidgetItem, QSizePolicy, QMessageBox, QInputDialog,
    QDialog, QProgressBar, QGroupBox, QFileDialog
)
from PyQt6.QtGui import QColor, QFont, QPixmap, QIcon
from PyQt6.QtCore import Qt, QTimer, QSize, QProcess

import configparser
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "SmartDiskDoctor"
CONFIG_FILE = CONFIG_DIR / "settings.json"

def load_settings():
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"language": "en"}

def save_settings(settings):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Ayarlar kaydedilemedi: {e}")


# Linux/Debian tabanlı sistemler için X11 zorlaması
os.environ["QT_QPA_PLATFORM"] = "xcb" # GNOME ortamında sıkıntısız açılması için.

class LanguageManager:
    def __init__(self, lang_code="en"):
        self.lang_code = lang_code
        self.config = configparser.ConfigParser()
        self.load_language(lang_code)

    def load_language(self, lang_code):
        self.lang_code = lang_code
        base_path = os.path.dirname(os.path.abspath(__file__))
        lang_file = os.path.join(base_path, "languages", f"{lang_code}.ini")
        if os.path.exists(lang_file):
            self.config.read(lang_file, encoding='utf-8')

    def get_available_languages(self):
        base_path = os.path.dirname(os.path.abspath(__file__))
        lang_dir = os.path.join(base_path, "languages")
        if not os.path.exists(lang_dir): 
            return ["tr"]
        return [f.replace(".ini", "") for f in os.listdir(lang_dir) if f.endswith(".ini")]

    def get(self, section, key, default=""):
        try:
            if self.config.has_section(section):
                return self.config.get(section, key, fallback=default)
            return default
        except:
            return default

# Global dil yöneticisi - Sınıflar başlamadan önce tanımlanmalıdır
user_settings = load_settings()
lang = LanguageManager(user_settings.get("language", "en"))

# smartctl ve disk bilgileri ile ilgili fonksiyonlar
def get_disk_list():
    """
    Sistemdeki diskleri JSON formatında listeler.
    """
    try:
        # -J parametresi çıktıyı JSON formatında verir
        output = subprocess.check_output(['lsblk', '-J', '-o', 'NAME,SIZE,TYPE,MODEL,VENDOR']).decode('utf-8')
        data = json.loads(output)
        disks = []
        
        for device in data.get('blockdevices', []):
            if device.get('type') == 'disk':
                disk_name = device.get('name', '')
                disk_size = device.get('size', '')
                model = device.get('model') or ''
                vendor = device.get('vendor') or ''
                
                full_model_vendor = f"{vendor} {model}".strip()
                full_name = f"{disk_name} ({disk_size}) - {full_model_vendor}".strip()

                disks.append({'path': f"/dev/{disk_name}", 'name': full_name})
        return disks
    except Exception as e:
        QMessageBox.critical(None, "Hata", f"Disk listesi alınamadı: {e}")
        return []

def get_smart_data(disk_path):
    """
    Belirtilen diskin SMART verilerini JSON formatında alır.
    """
    device_types = ['auto', 'nvme', 'sat', 'ata']

    for dev_type in device_types:
        try:
            # -j parametresi ile tüm veriyi tek seferde JSON olarak alıyoruz
            process = subprocess.run(
                ['smartctl', '-a', '-j', '-d', dev_type, disk_path],
                capture_output=True, text=True, timeout=20
            )
            
            # smartctl bazen hata kodu döndürse bile JSON çıktısı verebilir, bu yüzden çıktıyı kontrol ediyoruz
            if process.stdout:
                data = json.loads(process.stdout)
                # SMART desteği kontrolü
                if not data.get("smart_support", {}).get("available", False):
                    continue
                return data, ""
                
        except Exception as e:
            continue

    return None, "SMART verisi alınamadı veya disk desteklemiyor."

def parse_smart_attributes(smart_json):
    """
    JSON verisinden SMART özniteliklerini standart bir liste formatına dönüştürür.
    """
    attributes = []
    
    # SATA/ATA Diskler için (ata_smart_attributes içinde yer alır)
    if "ata_smart_attributes" in smart_json:
        table = smart_json["ata_smart_attributes"].get("table", [])
        for item in table:
            attributes.append({
                "ID": item.get("id", "-"),
                "Name": item.get("name", "Unknown"),
                "Current": item.get("value", "-"),
                "Worst": item.get("worst", "-"),
                "Threshold": item.get("thresh", 0),
                "Raw_Value": item.get("raw", {}).get("string", "0")
            })
            
    # NVMe Diskler için (nvme_smart_health_information_log içinde yer alır)
    elif "nvme_smart_health_information_log" in smart_json:
        log = smart_json["nvme_smart_health_information_log"]
        for key, value in log.items():
            # NVMe verilerini SATA formatına benzetiyoruz ki tablo yapısı bozulmasın
            attributes.append({
                "ID": "-",
                "Name": key.replace("_", " ").title(),
                "Current": "-",
                "Worst": "-",
                "Threshold": 0,
                "Raw_Value": str(value)
            })
            
    return attributes

def parse_smart_info(smart_json):
    """
    JSON verisinden genel disk bilgilerini çeker.
    """
    info = {}
    
    # Model ve Seri No (Her iki tipte de ortak alanlar)
    info["Device Model"] = smart_json.get("model_name", "Bilinmiyor")
    info["Serial Number"] = smart_json.get("serial_number", "Bilinmiyor")
    info["Firmware Version"] = smart_json.get("firmware_version", "Bilinmiyor")
    
    # Kapasite (JSON'da user_capacity altında yapılandırılmış gelir)
    cap = smart_json.get("user_capacity", {})
    info["User Capacity"] = cap.get("temp_test_string", f"{cap.get('bytes', 0) // (1024**3)} GB") if cap else "Bilinmiyor"
    
    # Dönüş Hızı ve SMART Durumu
    # NVMe'de rotation_rate gelmez, bu yüzden raporun önerdiği gibi kontrol ediyoruz
    rot = smart_json.get("rotation_rate", 0)
    if rot == 0:
        info["Rotation Rate"] = "Solid State Device (NVMe/SSD)"
    else:
        info["Rotation Rate"] = f"{rot} RPM"
        
    status = smart_json.get("smart_status", {})
    info["SMART Supported"] = "Passed / OK" if status.get("passed") else "Check Needed"
    
    return info

def calculate_health_score(attributes, disk_info):
    score = 100
    critical_map = {
        5: 15, 173: 10, 177: 10, 187: 10, 196: 10,
        197: 20, 198: 20, 199: 5, 232: 15, 233: 20
    }
    warnings = []

    critical_txt = lang.get("General", "Status_Critical", "KRİTİK")
    
    for attr in attributes:
        if attr["Threshold"] > 0 and attr["Current"] <= attr["Threshold"]:
            score -= 30
            warnings.append(f"{critical_txt}: {attr['Name']} {lang.get('General', 'BelowThreshold', 'eşik değerinin altında!')}")

        attr_id = attr["ID"]
        if attr_id in critical_map:
            try:
                raw_str = str(attr["Raw_Value"]).split()[0]
                raw_val = int(''.join(filter(str.isdigit, raw_str))) if any(c.isdigit() for c in raw_str) else 0
                if raw_val > 0:
                    if attr_id == 232 and raw_val >= 10: continue
                    info_txt = lang.get("General", "Info", "BİLGİ")
                    warning_txt = lang.get("General", "Status_Critical", "UYARI")
                    if attr_id in [173, 233]:
                        score -= 2
                        warnings.append(f"{lang.get('General', 'SSD_Wear', 'SSD Yıpranma Belirtisi')} ({attr['Name']})")
                    else:
                        score -= critical_map[attr_id]
                        warnings.append(f"{attr['Name']} {lang.get('General', 'ErrorRecord', 'hata kaydı var')} ({lang.get('Table', 'RawValue', 'Değer')}: {raw_val})")
            except: pass

    score = max(0, min(100, score))
    if score == 100: status = lang.get("General", "Status_Excellent", "MÜKEMMEL"); status_note = lang.get("General", "Note_Excellent", "Disk durumu mükemmel.")
    elif score >= 90: status = lang.get("General", "Status_Good", "İYİ"); status_note = lang.get("General", "Note_Good", "Disk durumu iyi.")
    elif score >= 75: status = lang.get("General", "Status_Medium", "ORTA"); status_note = lang.get("General", "Note_Medium", "Disk durumu orta. Yedekleme önerilir.")
    else: status = lang.get("General", "Status_Critical", "KRİTİK"); status_note = lang.get("General", "Note_Critical", "DİKKAT! Acilen yedek alın!")

    # --- Saat Bazlı Dürüst Ömür Tahmini ---
    power_on_hours = 0
    percentage_used = 0
    
    for attr in attributes:
        attr_name = str(attr["Name"]).lower()
        # SATA için ID 9, NVMe için "Power On Hours" metni
        if attr["ID"] == 9 or "power on hours" in attr_name:
            try:
                # NVMe'de "1,234" veya "1234 hours" gibi gelebilir, temizliyoruz
                raw_str = str(attr["Raw_Value"]).replace(',', '').replace('.', '').split()[0]
                power_on_hours = int(''.join(filter(str.isdigit, raw_str)))
            except: pass
        
        # NVMe özel: Kullanılan Ömür Yüzdesi
        if "percentage used" in attr_name:
            try:
                raw_str = str(attr["Raw_Value"]).replace('%', '').strip()
                percentage_used = int(''.join(filter(str.isdigit, raw_str)))
                # NVMe'de doğrudan sağlık puanını bu veriden türetebiliriz
                # score = min(score, 100 - percentage_used) <-- diskin ömrü sağlık puanını düşürmemelidir.
            except: pass

    # disk_info üzerinden SSD/HDD ayrımı
    is_ssd = "Solid State" in disk_info.get("Rotation Rate", "")
    max_hours = 50000 if is_ssd else 40000 
    
    if power_on_hours > 0:
        remaining_hours = max(0, max_hours - power_on_hours)
        years = int(remaining_hours // 8760)
        months = int((remaining_hours % 8760) // 720)
        
        if remaining_hours > 0:
            approx_txt = lang.get("General", "Approx", "Yaklaşık")
            year_txt = lang.get("General", "Year", "Yıl")
            month_txt = lang.get("General", "Month", "Ay")
            
            time_str = f"{approx_txt} {years} {year_txt}, {months} {month_txt}" if years > 0 else f"{approx_txt} {months} {month_txt}"
            estimated_life = f"{time_str}"
        else:
            estimated_life = lang.get("General", "RiskLimit", "Riskli (Beklenen çalışma ömrü sınırı aşıldı)")
    else:
        estimated_life = lang.get("General", "Unknown", "Bilinmiyor")

    notes = f"{lang.get('General', 'Summary', 'Özet')}: {status_note}\n{lang.get('General', 'Health', 'Sağlık')}: %{score}\n{lang.get('General', 'EstimatedLife', 'Tahmini Kalan Ömür')}: {estimated_life} ({lang.get('General', 'Approx', 'Yaklaşık')})".replace('::', ':')
    if warnings:
        notes += f"\n\n{lang.get('General', 'TechnicalIssues', 'Tespit Edilen Teknik Sorunlar')}\n" + "\n".join([f"- {w}" for w in warnings])
        
    return score, status, notes, estimated_life

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lang.get("About", "Title", "Smart Disk Doctor Hakkında"))
        self.setMinimumSize(400, 380)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel(lang.get("General", "AppName", "Smart Disk Doctor v2.0.1"))
        title_label.setFont(QFont("Liberation Sans", 18, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        description = lang.get("About", "Description", "Bu program, mekanik diskler ve SSD'lerin sağlığını kontrol ederek size SMART bilgileri ile beraber sunan HDD Sentinel benzeri bir programdır.")
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc_label)

        details_layout = QVBoxLayout()
        details = [
            f"<b>{lang.get('About', 'Version', 'Sürüm')}:</b> 2.0.1",
            f"<b>{lang.get('About', 'License', 'Lisans')}:</b> GNU GPLv3",
            f"<b>{lang.get('About', 'Language', 'Programlama Dili')}:</b> Python3",
            f"<b>{lang.get('About', 'Gui', 'GUI/UX')}:</b> PyQt6",
            f"<b>{lang.get('About', 'Developer', 'Geliştirici')}:</b> A. Serhat KILIÇOĞLU (shampuan)",
            '<b>GitHub:</b> <a href="https://www.github.com/shampuan" style="color: #3498db; text-decoration: none;">www.github.com/shampuan</a>'
        ]

        for text in details:
            lbl = QLabel(text)
            lbl.setOpenExternalLinks(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            details_layout.addWidget(lbl)
        
        layout.addLayout(details_layout)

        guarantee_label = QLabel("<i>Bu program hiçbir garanti getirmez.</i>")
        guarantee_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(guarantee_label)

        copyright_label = QLabel("© 2026 - A. Serhat KILIÇOĞLU")
        copyright_label.setFont(QFont("Liberation Sans", 9))
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_label)

        layout.addSpacing(10)
        ok_button = QPushButton(lang.get("About", "Ok", "Tamam"))
        ok_button.setFixedWidth(100)
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)
        
class SecureEraseDialog(QDialog):
    def __init__(self, disk_path, parent=None):
        super().__init__(parent)
        self.disk_path = disk_path
        self.setWindowTitle(f"{lang.get('SecureErase', 'Title', 'Diski Güvenli Sil')}: {self.disk_path}")
        self.setMinimumSize(380, 250)
        
        self.shred_process = QProcess(self)
        self.shred_process.readyReadStandardError.connect(self.update_progress)
        self.shred_process.finished.connect(self.shred_finished)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Bilgilendirme metni
        info_text = lang.get("SecureErase", "Info", "Bu işlem, HDD'nizi ya da SSD'nizi satışa çıkarmadan evvel...")
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Kırmızı uyarı metni
        warning_label = QLabel(f"<b>{lang.get('General', 'Status_Critical', 'DİKKAT')}:</b> {self.disk_path} {lang.get('SecureErase', 'Warning', 'üzerindeki tüm veriler kalıcı olarak silinecektir!')}")
        warning_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton(lang.get("SecureErase", "Start", "İşlemi Başlat"))
        self.start_btn.clicked.connect(self.start_shred)
        
        self.stop_btn = QPushButton(lang.get("SecureErase", "Stop", "Durdur"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_shred)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

    def start_shred(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.shred_process.start('shred', ['-v', '-n', '1', self.disk_path])

    def stop_shred(self):
        if self.shred_process.state() == QProcess.ProcessState.Running:
            self.shred_process.terminate()
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(True)
            QMessageBox.warning(self, lang.get("SecureErase", "Stopped", "Durduruldu"), lang.get("SecureErase", "StoppedMsg", "İşlem kullanıcı tarafından kesildi."))

    def update_progress(self):
        data = self.shred_process.readAllStandardError().data().decode(errors='ignore')
        found = re.findall(r'(\d+)%', data)
        if found:
            self.progress_bar.setValue(int(found[-1]))

    def shred_finished(self):
        self.progress_bar.setValue(100)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        QMessageBox.information(self, lang.get("General", "Completed", "Tamamlandı"), lang.get("SecureErase", "FinishMsg", "Güvenli silme işlemi başarıyla bitti."))

class DetailedAnalysisDialog(QDialog):
    def __init__(self, disk_path, parent=None):
        super().__init__(parent)
        self.disk_path = disk_path
        self.setWindowTitle(f"{lang.get('General', 'DetailedAnalysis', 'Detaylı SMART Analizi')}: {self.disk_path}")
        self.setMinimumSize(800, 600)
        self.init_ui()
        self.run_analysis()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Monospace", 10))
        layout.addWidget(self.output_text)
        
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton(lang.get("General", "SaveFile", "Dosyaya Kaydet (.txt)"))
        self.save_button.clicked.connect(self.save_to_file)
        
        close_button = QPushButton(lang.get("General", "Close", "Kapat"))
        close_button.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(close_button)
        layout.addLayout(btn_layout)

    def generate_report_from_json(self, data):
        """JSON verisinden çok detaylı ve kapsamlı bir rapor oluşturur."""
        report = []
        report.append("="*80)
        report.append(f"{lang.get('General', 'ReportTitle', 'DETAYLI SMART ANALİZİ').center(80)}")
        report.append("="*80 + "\n")

        # --- CİHAZ BİLGİLERİ ---
        report.append(f"[ {lang.get('General', 'DeviceInformation', 'CİHAZ BİLGİLERİ')} ]")
        report.append(f"Model             : {data.get('model_name', 'Bilinmiyor')}")
        report.append(f"Seri Numarası     : {data.get('serial_number', 'Bilinmiyor')}")
        report.append(f"Firmware Sürümü   : {data.get('firmware_version', 'Bilinmiyor')}")
        
        cap = data.get('user_capacity', {})
        report.append(f"Kapasite          : {cap.get('temp_test_string', 'Bilinmiyor')}")
        
        if "rotation_rate" in data:
            rot = data.get("rotation_rate")
            report.append(f"Dönüş Hızı        : {rot if rot != 0 else 'SSD (N/A)'} RPM")
        
        status = data.get('smart_status', {})
        report.append(f"SMART Durumu      : {'PASSED' if status.get('passed') else 'DİKKAT / HATA'}")
        report.append("-" * 80)

        # --- NVMe ÖZEL VERİLERİ (Varsa) ---
        if "nvme_smart_health_information_log" in data:
            report.append("\n[ NVMe SAĞLIK VE KULLANIM LOGLARI ]")
            nvme_log = data["nvme_smart_health_information_log"]
            for k, v in nvme_log.items():
                label = k.replace('_', ' ').title()
                report.append(f"{label:<35}: {v}")

        # --- SATA / ATA ÖZNİTELİK TABLOSU (Varsa) ---
        if "ata_smart_attributes" in data:
            report.append("\n[ SMART ÖZNİTELİK TABLOSU ]")
            report.append(f"{'ID':<4} {'Öznitelik Adı':<30} {'Değer':<6} {'En Kötü':<8} {'Eşik':<6} {'Ham Veri'}")
            report.append("-" * 80)
            table = data["ata_smart_attributes"].get("table", [])
            for attr in table:
                report.append(
                    f"{attr.get('id', '-'):<4} "
                    f"{attr.get('name', 'Bilinmiyor')[:29]:<30} "
                    f"{attr.get('value', '-'):<6} "
                    f"{attr.get('worst', '-'):<8} "
                    f"{attr.get('thresh', '-'):<6} "
                    f"{attr.get('raw', {}).get('string', '0')}"
                )

        # --- KENDİ KENDİNE TEST (SELF-TEST) LOGLARI ---
        test_log = data.get('ata_smart_self_test_log', {}).get('standard', {})
        if test_log and test_log.get('table'):
            report.append(f"\n[ {lang.get('General', 'SelfTestHistory', 'SELF-TEST GEÇMİŞİ')} ]")
            for entry in test_log.get('table', []):
                st_status = entry.get('status', {}).get('string', 'Bilinmiyor')
                report.append(f"- Test: {entry.get('type', {}).get('string'):<15} Durum: {st_status}")

        # --- SMART HATA KAYITLARI ---
        error_log = data.get('smart_error_log', {})
        if error_log:
            count = error_log.get('summary', {}).get('count', 0)
            report.append(f"\n[ {lang.get('General', 'ErrorLogs', 'HATA KAYITLARI')} ]")
            report.append(f"{lang.get('General', 'TotalErrors', 'Toplam kayıtlı hata sayısı')}: {count}")
            if count > 0 and 'table' in error_log:
                report.append(lang.get('General', 'LogNote', 'Son hata detayları sistem loglarında mevcuttur.'))

        return "\n".join(report)

    def run_analysis(self):
        """Terminaldeki tam smartctl çıktısını olduğu gibi pencereye yansıtır."""
        try:
            # -a parametresi ile terminaldeki tam raporu alıyoruz.
            # JSON yerine ham metin (plain text) olarak çekiyoruz ki hiçbir detay kaybolmasın.
            process = subprocess.run(
                ['smartctl', '-a', self.disk_path],
                capture_output=True, text=True, timeout=25
            )
            
            if process.stdout:
                # Terminaldeki çıktının aynısını doğrudan QTextEdit içine aktar
                self.output_text.setText(process.stdout)
                
                # Eğer çıktı çok kısaysa veya hata mesajı içeriyorsa uyarı ekle
                if "SMART support is: Available" not in process.stdout:
                    self.output_text.append(f"\n{'='*40}\nNOT: Bu disk için tam SMART desteği sağlanamıyor olabilir.")
            else:
                error_msg = process.stderr if process.stderr else "smartctl boş çıktı döndürdü."
                self.output_text.setText(f"Hata: Analiz verisi alınamadı.\n\nDetay:\n{error_msg}")
                
        except Exception as e:
            self.output_text.setText(f"Bilinmeyen bir hata oluştu:\n{str(e)}")

    def save_to_file(self):
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Analizi Kaydet", f"smart_analiz_{self.disk_path.replace('/', '_')}.txt", "Metin Dosyaları (*.txt)")
        
        if file_path:
            content = self.output_text.toPlainText()
            # Windows uyumlu satır sonları (CRLF) ile kaydetme
            with open(file_path, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write(content)
            QMessageBox.information(self, lang.get("General", "Success", "Success"), lang.get("General", "Success", "Success"))

class ZeusHDDDoctor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(lang.get("General", "AppName", "Smart Disk Doctor v2.0.1"))
        self.setGeometry(100, 100, 1100, 750)

        self.shred_process = QProcess(self)
        self.shred_process.readyReadStandardError.connect(self.update_shred_progress)
        self.shred_process.finished.connect(self.shred_finished)
        self.shred_process.errorOccurred.connect(self.shred_error_occurred)

        self.stderr_buffer = ""
        # Uygulama ikonu atama (Dinamik yol ile)
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "smartdocicon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.init_ui()
        self.load_disks()
        
    def change_language_dialog(self):
        # Dil dosya adlarını (tr, en...) yerel isimlere bağlayan sözlük
        languages = {
            "Türkçe": "tr", 
            "English": "en", 
            "Deutsch": "de", 
            "Français": "fr", 
            "Italiano": "it", 
            "Español": "es", 
            "Русский": "ru", 
            "日本語": "ja"
        }
        
        # Sadece sistemde dosyası olan dilleri filtrele
        available_files = lang.get_available_languages()
        display_list = [name for name, code in languages.items() if code in available_files]
        
        # Eğer sözlükte olmayan bir .ini dosyası varsa onu da listeye ekle (Hata önleyici)
        for code in available_files:
            if code not in languages.values():
                display_list.append(code)

        choice_name, ok = QInputDialog.getItem(
            self, 
            lang.get("General", "Language", "Language"), 
            lang.get("General", "Language", "Language") + ":", 
            display_list, 
            0, 
            False
        )
        
        if ok and choice_name:
            # Seçilen uzun isimden arka plandaki kısa kodu al (Örn: "Русский" -> "ru")
            choice_code = languages.get(choice_name, choice_name)
            
            # Ayarları kaydet ve dili yükle
            user_settings["language"] = choice_code
            save_settings(user_settings)
            lang.load_language(choice_code)
            
            QMessageBox.information(self, lang.get("General", "Info", "Info"), lang.get("General", "Success", "Success"))
            
            # UI'ı tazele
            old_widget = self.centralWidget()
            if old_widget:
                old_widget.deleteLater()
            self.init_ui() 
            self.load_disks()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel(lang.get("General", "Disks", "Diskler:")), 0)
        
        self.disk_list_widget = QListWidget()
        self.disk_list_widget.setFixedWidth(300)
        self.disk_list_widget.itemClicked.connect(self.on_disk_selected)
        left_panel.addWidget(self.disk_list_widget, 1)

        self.zeus_logo_label = QLabel()
        # Betiğin olduğu dizini bul ve amblem ismini yanına ekle
        base_path = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_path, "smartdocicon.png")
        
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            self.zeus_logo_label.setPixmap(pixmap)
            self.zeus_logo_label.setScaledContents(True)
            self.zeus_logo_label.setFixedSize(200, 220)
        else:
            self.zeus_logo_label.setText("Amblem Yüklenemedi")
        
        self.zeus_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_panel.addStretch()
        left_panel.addWidget(self.zeus_logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout.addLayout(left_panel)

        right_panel = QVBoxLayout()
        self.disk_details_text = QTextEdit()
        self.disk_details_text.setReadOnly(True)
        self.disk_details_text.setFixedHeight(150)
        right_panel.addWidget(QLabel(lang.get("General", "SelectedDiskInfo", "Seçili Disk Bilgileri:")))
        right_panel.addWidget(self.disk_details_text)

        self.health_status_label = QLabel(f"{lang.get('General', 'Health', 'Sağlık')} N/A".replace('::', ':'))
        self.health_status_label.setFont(QFont("Liberation Sans", 16, QFont.Weight.Bold))
        self.health_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.health_status_label.setStyleSheet("")
        right_panel.addWidget(self.health_status_label)

        self.notes_text = QTextEdit()
        self.notes_text.setFixedHeight(125)
        self.notes_text.setReadOnly(True)
        right_panel.addWidget(self.notes_text)

        # Diski Satışa Hazırla (Güvenli Silme) Çerçevesi
        from PyQt6.QtWidgets import QGroupBox, QProgressBar
        
        # Butonlar için yatay bir yerleşim
        action_btn_layout = QHBoxLayout()
        
        self.secure_erase_nav_button = QPushButton(lang.get("General", "SecureErase", "Diski Satışa Hazırla (Güvenli Sil)"))
        self.secure_erase_nav_button.setFixedHeight(35)
        self.secure_erase_nav_button.clicked.connect(self.open_secure_erase_dialog)
        
        self.detailed_analysis_button = QPushButton(lang.get("General", "DetailedAnalysis", "Detaylı Analiz Göster"))
        self.detailed_analysis_button.setFixedHeight(35)
        self.detailed_analysis_button.clicked.connect(self.show_detailed_analysis)
        
        action_btn_layout.addWidget(self.secure_erase_nav_button)
        action_btn_layout.addWidget(self.detailed_analysis_button)
        right_panel.addLayout(action_btn_layout)

        self.lang_button = QPushButton(lang.get("General", "Language", "Dil"))
        self.attributes_table = QTableWidget()
        headers = [
            lang.get("Table", "ID", "ID"), lang.get("Table", "Name", "Name"),
            lang.get("Table", "Current", "Current"), lang.get("Table", "Worst", "Worst"),
            lang.get("Table", "Threshold", "Threshold"), lang.get("Table", "Type", "Type"),
            lang.get("Table", "RawValue", "Raw Value")
        ]
        self.attributes_table.setColumnCount(len(headers))
        self.attributes_table.setHorizontalHeaderLabels(headers)
        # Sütun genişliklerini içeriğe ve ihtiyaca göre özelleştirme
        header = self.attributes_table.horizontalHeader()
        
        # ID, Current, Worst, Threshold ve Type gibi kısa veriler için içeriğe göre daraltma
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Current
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Worst
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Threshold
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Type

        # Name ve Raw Value gibi uzun açıklamalar için esnetme (Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)          # Name
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)          # Raw Value
        right_panel.addWidget(self.attributes_table, 1) # 1 değeri tablonun esnemesini sağlar

        btn_layout = QHBoxLayout()
        
        self.lang_button = QPushButton(lang.get("General", "Language", "Dil"))
        self.lang_button.clicked.connect(self.change_language_dialog)
        self.about_button = QPushButton(lang.get("General", "About", "Hakkında"))
        self.about_button.clicked.connect(self.show_about_dialog)
        self.refresh_button = QPushButton(lang.get("General", "Refresh", "Yenile"))
        self.refresh_button.clicked.connect(self.refresh_selected_disk)
        btn_layout.addStretch()
        btn_layout.addWidget(self.about_button)
        btn_layout.addWidget(self.lang_button)
        btn_layout.addWidget(self.refresh_button)
        right_panel.addLayout(btn_layout)

        main_layout.addLayout(right_panel, 1)

    def load_disks(self):
        self.disk_list_widget.clear()
        self.disks = get_disk_list()
        for disk in self.disks:
            item = QListWidgetItem(disk['name'])
            item.setData(Qt.ItemDataRole.UserRole, disk['path'])
            self.disk_list_widget.addItem(item)
        if self.disks:
            self.disk_list_widget.setCurrentRow(0)
            self.on_disk_selected(self.disk_list_widget.currentItem())

    def on_disk_selected(self, item):
        if item: self.display_disk_data(item.data(Qt.ItemDataRole.UserRole))

    def refresh_selected_disk(self):
        # Önce sistemdeki güncel disk listesini yükle (Yeni takılan cihazlar için)
        self.load_disks()
        
        # Sonra seçili olan (veya yeniden yüklenen) diskin verilerini tazele
        item = self.disk_list_widget.currentItem()
        if item: 
            self.display_disk_data(item.data(Qt.ItemDataRole.UserRole))

    def show_about_dialog(self):
        AboutDialog(self).exec()
        
    def open_secure_erase_dialog(self):
        item = self.disk_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, lang.get("General", "Error", "Hata"), lang.get("General", "SelectDiskWarning", "Lütfen önce bir disk seçin."))
            return
        
        disk_path = item.data(Qt.ItemDataRole.UserRole)
        dialog = SecureEraseDialog(disk_path, self)
        dialog.exec()
    
    def show_detailed_analysis(self):
        item = self.disk_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, lang.get("General", "Error", "Hata"), lang.get("General", "SelectDiskWarning", "Lütfen önce bir disk seçin."))
            return
        
        disk_path = item.data(Qt.ItemDataRole.UserRole)
        dialog = DetailedAnalysisDialog(disk_path, self)
        dialog.exec()
        

    def initiate_secure_erase(self):
        item = self.disk_list_widget.currentItem()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.warning(self, "ONAY", f"{path} SİLİNECEK! Emin misiniz?", 
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.secure_erase_button.setEnabled(False)
            # -n 1: Sadece 1 kez rastgele veri yaz (Hızlı ve güvenli)
            self.shred_process.start('shred', ['-v', '-n', '1', path])

    def update_shred_progress(self):
        # Okunan veriyi decode et ve tampona ekle
        data = self.shred_process.readAllStandardError().data().decode(errors='ignore')
        self.stderr_buffer += data
        
        # En güncel yüzde bilgisini bul
        found_percentages = re.findall(r'(\d+)%', self.stderr_buffer)
        if found_percentages:
            last_percent = found_percentages[-1]
            self.progress_bar.setValue(int(last_percent))
            # Tamponun aşırı büyümesini engellemek için son kısmı tutalım
            if len(self.stderr_buffer) > 1000:
                self.stderr_buffer = self.stderr_buffer[-500:]

    def shred_finished(self, exit_code, exit_status):
        self.secure_erase_button.setEnabled(True)
        self.progress_bar.setValue(100)
        QMessageBox.information(self, lang.get("General", "Info", "Bilgi"), lang.get("General", "Completed", "İşlem tamamlandı."))

    def shred_error_occurred(self, error):
        self.secure_erase_button.setEnabled(True)
        QMessageBox.critical(self, lang.get("General", "Error", "Hata"), f"{lang.get('General', 'Error', 'Hata')}: {error}")

    def display_disk_data(self, disk_path):
        smart_json, err = get_smart_data(disk_path)
        if smart_json:
            self.disk_details_text.clear() 
            self.disk_details_text.setStyleSheet("color: #3498db; font-weight: bold;") 
            
            # Eski attr_out yerine smart_json gönderiyoruz
            attrs = parse_smart_attributes(smart_json)
            info = parse_smart_info(smart_json)
            
            score, status, notes, life = calculate_health_score(attrs, info)
            
            # Tablo verilerinden saat ve sıcaklığı çekiyoruz
            raw_poh = next((a['Raw_Value'] for a in attrs if a['ID'] == 9 or "power on hours" in str(a['Name']).lower()), None)
            if raw_poh:
                try:
                    # JSON'dan gelen veri bazen string bazen int olabilir, temizliyoruz
                    hours = int(''.join(filter(str.isdigit, str(raw_poh))))
                    years = hours // 8760
                    months = (hours % 8760) // 720
                    h_txt = lang.get("General", "Hour", "Saat")
                    y_txt = lang.get("General", "Year", "Yıl")
                    m_txt = lang.get("General", "Month", "Ay")
                    poh_text = f"{hours} {h_txt} ({years} {y_txt}, {months} {m_txt})"
                except:
                    poh_text = str(raw_poh)
            else:
                poh_text = lang.get("General", "Unknown", "Bilinmiyor")

            # Sıcaklık bilgisini al
            raw_temp = next((a['Raw_Value'] for a in attrs if a['ID'] in [194, 190] or "temperature" in str(a['Name']).lower()), None)
            if raw_temp:
                temp_val = str(raw_temp).split()[0].replace('°', '').strip()
                temp_text = f"{temp_val}°C"
            else:
                temp_text = lang.get("General", "Unknown", "Bilinmiyor")
            
            # Renk tonları
            if score >= 85:
                color = "#27ae60"  
                bg_color = "#0d1f14" 
            elif score >= 70:
                color = "#f1c40f"  
                bg_color = "#241e02" 
            elif score >= 60:
                color = "#e67e22"  
                bg_color = "#261505" 
            else:
                color = "#c0392b"  
                bg_color = "#1f0a08" 

            self.health_status_label.setText(f"{lang.get('General', 'Health', 'Sağlık')}: %{score} ({status})".replace('::', ':'))
            self.health_status_label.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold; border-radius: 8px; padding: 15px; font-size: 18px;")
            
            self.notes_text.setText(notes)
            self.notes_text.setStyleSheet(f"background-color: {bg_color}; color: #ecf0f1; border: 1px solid {color}; border-radius: 5px; padding: 8px;")
            
            details = (f"{lang.get('Details', 'Model', 'Cihaz Modeli')}: {info.get('Device Model', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'Serial', 'Seri Numarası')}: {info.get('Serial Number', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'Capacity', 'Kapasite')}: {info.get('User Capacity', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'Firmware', 'Firmware')}: {info.get('Firmware Version', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'Rotation', 'Dönüş Hızı')}: {info.get('Rotation Rate', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'SmartStatus', 'SMART Durumu')}: {info.get('SMART Supported', 'Bilinmiyor')}\n"
                       f"{lang.get('Details', 'TotalWork', 'Toplam Çalışma')}: {poh_text}\n"
                       f"{lang.get('Details', 'Temperature', 'Sıcaklık')}: {temp_text}")
            
            self.disk_details_text.setPlainText(details)
            
            # Tabloyu doldur
            self.attributes_table.setRowCount(len(attrs))
            for i, a in enumerate(attrs):
                self.attributes_table.setItem(i, 0, QTableWidgetItem(str(a['ID'])))
                self.attributes_table.setItem(i, 1, QTableWidgetItem(a['Name']))
                self.attributes_table.setItem(i, 2, QTableWidgetItem(str(a.get('Current', '-'))))
                self.attributes_table.setItem(i, 3, QTableWidgetItem(str(a.get('Worst', '-'))))
                self.attributes_table.setItem(i, 4, QTableWidgetItem(str(a.get('Threshold', 0))))
                
                type_val = lang.get("Table", "PreFail", "Pre-fail") if int(str(a.get('Threshold', 0))) > 0 else lang.get("Table", "OldAge", "Old_age")
                self.attributes_table.setItem(i, 5, QTableWidgetItem(type_val))
                self.attributes_table.setItem(i, 6, QTableWidgetItem(str(a['Raw_Value'])))
        else:
            self.disk_details_text.setStyleSheet("color: #c0392b;") 
            self.health_status_label.setText("HATA")
            self.notes_text.setText(err)

if __name__ == "__main__":
    # Sistem varsayılan ölçeklendirmesini kullan
    # Bu özelliği devre dışı bıraktım ki sistem temasına göre uyarlansın. 
    
    if os.geteuid() != 0:
        # Mevcut ekran (Display) ve yetki (XAuthority) bilgilerini alıyoruz
        display_var = os.environ.get('DISPLAY')
        xauth_var = os.environ.get('XAUTHORITY')
        script_path = os.path.abspath(sys.argv[0])

        # pkexec'e bu değişkenleri paslıyoruz ki root ekranı açabilsin
        command = ['pkexec', 'env', 
                   f'DISPLAY={display_var}', 
                   f'XAUTHORITY={xauth_var}', 
                   sys.executable, script_path] + sys.argv[1:]
        
        try:
            subprocess.run(command, check=True)
            sys.exit(0)
        except Exception as e:
            print(f"Yetkilendirme hatası: {e}")
            sys.exit(1)

    # Sistem temasını (GTK/Dark) zorlamak için argüman listesine platform temasını ekliyoruz
    # Bu yöntem, çevre değişkenlerinden daha baskındır.
    sys_args = sys.argv + ['-platformtheme', 'gtk3']
    app = QApplication(sys_args)
    app.setFont(QFont("Liberation Sans", 10))
    
    # Qt6'nın sistemdeki renk şemasını (koyu/açık) otomatik algılaması için
    app.setStyle("Fusion")
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Fusion"
    
    window = ZeusHDDDoctor()
    window.show()
    sys.exit(app.exec())
