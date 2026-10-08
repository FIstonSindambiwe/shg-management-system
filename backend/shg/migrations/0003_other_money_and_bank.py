from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shg', '0002_meeting_submission_and_rules'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='carried_by',
            field=models.CharField(blank=True, help_text='Who took the money to the bank.', max_length=120),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='type',
            field=models.CharField(choices=[('SHARE', 'Imigabane (shares)'), ('INGOBOKA_IN', 'Ingoboka (social fund) contribution'), ('INGOBOKA_OUT', 'Ingoboka (social fund) payout'), ('MUTUELLE', 'Mutuelle saving'), ('FINE_PAYMENT', 'Ibihano (fine) paid'), ('LOAN_ISSUE', 'Inguzanyo (loan) given'), ('LOAN_RETURN', 'Ayishyuwe (loan returned)'), ('INTEREST', 'Inyungu (interest paid)'), ('EXPENSE', 'Group expense'), ('OTHER_INCOME', 'Other money in'), ('BANK_DEPOSIT', 'Taken to the bank')], max_length=15),
        ),
    ]