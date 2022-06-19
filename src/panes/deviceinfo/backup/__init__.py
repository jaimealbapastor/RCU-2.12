from .BackupController import BackupController
from .Backup import Backup
from .BackupFile import BackupFile

backup_types = {
    'Full (OS + Data)': [
        ['mmcblk1boot0', 'bin', '/dev/mmcblk1boot0'],
        ['mmcblk1boot1', 'bin', '/dev/mmcblk1boot1'],
        ['mmcblk1', 'bin', '/dev/mmcblk1']],
    'Only OS': [
        ['mmcblk1boot0', 'bin', '/dev/mmcblk1boot0'],
        ['mmcblk1boot1', 'bin', '/dev/mmcblk1boot1'],
        ['mmcblk1p1', 'bin', '/dev/mmcblk1p1'],
        ['mmcblk1p2', 'bin', '/dev/mmcblk1p2'],
        ['mmcblk1p3', 'bin', '/dev/mmcblk1p3']],
    'Only Data': [
        ['mmcblk1p5', 'bin', '/dev/mmcblk1p5'],
        ['mmcblk1p6', 'bin', '/dev/mmcblk1p6'],
        ['mmcblk1p7', 'bin', '/dev/mmcblk1p7']]
    }
