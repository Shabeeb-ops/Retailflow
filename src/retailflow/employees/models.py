from django.db import models

import company
from accounts.models import User
from company.models import Company


class Employee(models.Model):
    ROLE_CHOICES = [
        ("MANAGER", "Manager"),
        ("CASHIER", "Cashier"),
        ("INVENTORY", "Inventory Staff"),
        ("CUSTOMER_SERVICE", "Customer Service"),
        ("HELPER", "Helper"),
        ("CLEANER", "Cleaner"),
        ("OTHER", "Other Staff"),

    ]
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="employee")

    user = models.OneToOneField(User,on_delete=models.SET_NULL,null=True,blank=True,related_name="employee")

    employee_id = models.CharField(max_length=20,unique=True,editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20,choices=ROLE_CHOICES)
    joining_date = models.DateField(auto_now_add=True)
    is_online = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "employee_id"],
                name="unique_employee_id_per_company",
            )
        ]

    def save(self, *args, **kwargs):

        if not self.employee_id:

            last_employee = Employee.objects.order_by(
                "-id"
            ).first()

            if last_employee:
                last_number = int(
                    last_employee.employee_id.replace("ID", "")
                )
                next_number = last_number + 1
            else:
                next_number = 1

            self.employee_id = f"ID{next_number:03d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.role